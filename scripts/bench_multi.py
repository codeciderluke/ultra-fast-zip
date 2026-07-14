"""UFZ vs existing formats (ZIP, tar.gz, tar.zst, tar.xz) benchmark.

- UFZ    : this project's format (zstd blocks + xxHash64, parallel extract)
- ZIP    : Python zipfile, deflate level 6 (per-file compression)
- tar.gz : bsdtar (native C), gzip level 6 (stream compression)
- tar.zst: bsdtar (native C), zstd level 6 — same codec as UFZ, single stream
- tar.xz : bsdtar (native C), LZMA level 6 — 7-Zip-family high-ratio proxy

Runs pack/unpack for every format on the same dataset, measuring time, size,
and integrity. Results are also written as JSON.

Usage: python scripts/bench_multi.py <dataset dir> <work dir>
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

from app.core.packer import PackOptions, pack
from app.core.unpacker import UnpackOptions, unpack

SRC = Path(sys.argv[1])
WORK = Path(sys.argv[2])
RESULT_JSON = WORK / "results.json"
TAR = r"C:\windows\system32\tar.exe"
LEVEL = 6
RUNS = 2  # run each job twice, take the minimum (mitigates cache/noise)

_CHUNK = 4 * 1024 * 1024


def snapshot(root: Path) -> dict:
    result = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full = Path(dirpath) / name
            crc = 0
            size = 0
            with open(full, "rb") as fp:
                while True:
                    chunk = fp.read(_CHUNK)
                    if not chunk:
                        break
                    crc = zlib.crc32(chunk, crc)
                    size += len(chunk)
            result[full.relative_to(root).as_posix()] = (size, crc & 0xFFFFFFFF)
    return result


def timed(fn) -> float:
    best = None
    for _ in range(RUNS):
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    return best


def run_tar(args: list[str]) -> None:
    proc = subprocess.run([TAR] + args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"tar failed: {proc.stderr[:500]}")


def clean(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    print("Snapshotting source...", flush=True)
    src_snap = snapshot(SRC)
    total_bytes = sum(s for s, _ in src_snap.values())
    print(f"  {len(src_snap):,} files, {total_bytes / 1048576:.1f} MB", flush=True)

    results = {"dataset": {"files": len(src_snap), "bytes": total_bytes}, "formats": {}}

    def record(name: str, archive: Path, pack_fn, unpack_fn, out_dir: Path):
        print(f"[{name}] pack...", flush=True)

        def do_pack():
            clean(archive)
            pack_fn()

        pack_s = timed(do_pack)
        size = archive.stat().st_size

        print(f"[{name}] unpack...", flush=True)

        def do_unpack():
            clean(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            unpack_fn()

        unpack_s = timed(do_unpack)

        ok = snapshot(out_dir) == src_snap
        results["formats"][name] = {
            "pack_s": round(pack_s, 2),
            "unpack_s": round(unpack_s, 2),
            "size": size,
            "ratio_pct": round(size / total_bytes * 100, 2),
            "integrity": ok,
        }
        print(f"  pack {pack_s:.1f}s / unpack {unpack_s:.1f}s / "
              f"{size / 1048576:.1f} MB ({size / total_bytes * 100:.1f}%) / "
              f"integrity {'PASS' if ok else 'FAIL'}", flush=True)
        clean(out_dir)

    # 1) UFZ
    ufz_file = WORK / "bench.ufz"
    record(
        "UFZ(zstd)", ufz_file,
        lambda: pack(SRC, ufz_file, PackOptions(block_size=8 * 1024 * 1024, level=LEVEL)),
        lambda: unpack(ufz_file, WORK / "out_ufz", UnpackOptions(threads=0, overwrite=True)),
        WORK / "out_ufz",
    )
    clean(ufz_file)

    # 2) ZIP (deflate) via Python zipfile
    zip_file = WORK / "bench.zip"

    def zip_pack():
        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED, compresslevel=LEVEL) as zf:
            for dirpath, _, filenames in os.walk(SRC):
                for fname in sorted(filenames):
                    full = Path(dirpath) / fname
                    zf.write(full, full.relative_to(SRC).as_posix())

    def zip_unpack():
        with zipfile.ZipFile(zip_file) as zf:
            zf.extractall(WORK / "out_zip")

    record("ZIP(deflate)", zip_file, zip_pack, zip_unpack, WORK / "out_zip")
    clean(zip_file)

    # 3-5) bsdtar family
    src_str = str(SRC)
    for name, fname, copt in [
        ("tar.gz(gzip)", "bench.tar.gz", ["--gzip", "--options", f"gzip:compression-level={LEVEL}"]),
        ("tar.zst(zstd)", "bench.tar.zst", ["--zstd", "--options", f"zstd:compression-level={LEVEL}"]),
        ("tar.xz(LZMA)", "bench.tar.xz", ["--xz", "--options", f"xz:compression-level={LEVEL}"]),
    ]:
        arc = WORK / fname
        out = WORK / f"out_{fname.replace('.', '_')}"
        record(
            name, arc,
            lambda a=arc, c=copt: run_tar(["-c"] + c + ["-f", str(a), "-C", src_str, "."]),
            lambda a=arc, o=out: run_tar(["-x", "-f", str(a), "-C", str(o)]),
            out,
        )
        clean(arc)

    RESULT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nResults saved: {RESULT_JSON}", flush=True)

    print("=" * 78)
    print(f"{'Format':<16}{'Pack(s)':>10}{'Unpack(s)':>10}{'Size(MB)':>12}{'Ratio':>9}{'Integ':>8}")
    print("-" * 78)
    for name, r in results["formats"].items():
        print(f"{name:<16}{r['pack_s']:>10.1f}{r['unpack_s']:>10.1f}"
              f"{r['size'] / 1048576:>12.1f}{r['ratio_pct']:>8.1f}%"
              f"{'PASS' if r['integrity'] else 'FAIL':>8}")
    print("=" * 78)


if __name__ == "__main__":
    main()
