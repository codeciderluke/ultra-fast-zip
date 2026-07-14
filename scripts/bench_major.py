"""UFZ vs mainstream archivers (7-Zip, WinRAR) benchmark.

Formats and tools:

- UFZ     : this project, zstd level 6, 8MB blocks (single-thread pack,
            parallel unpack)
- ZIP     : 7-Zip 7z.exe, deflate, normal (-mx5), multithreaded
- 7z      : 7-Zip 7z.exe, LZMA2, normal (-mx5), multithreaded
- RAR     : WinRAR Rar.exe, normal (-m3), multithreaded
- tar.zst : bsdtar, zstd level 6 — same-codec single-stream reference

Each job runs twice (minimum taken); restored trees are verified by full
CRC32 against the source. Results are written as JSON.

Usage: python scripts/bench_major.py <dataset dir> <work dir>
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
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
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"
RAR = r"C:\Program Files\WinRAR\Rar.exe"
TAR = shutil.which("tar")
RUNS = 2

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


def run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed ({proc.returncode}): {proc.stderr[:400] or proc.stdout[:400]}")


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

    src_str = str(SRC)

    # UFZ (this project)
    ufz_file = WORK / "bench.ufz"
    record(
        "UFZ (zstd-6)", ufz_file,
        lambda: pack(SRC, ufz_file, PackOptions(block_size=8 * 1024 * 1024, level=6)),
        lambda: unpack(ufz_file, WORK / "out_ufz", UnpackOptions(threads=0, overwrite=True)),
        WORK / "out_ufz",
    )
    clean(ufz_file)

    # ZIP via 7-Zip (deflate, normal). Trailing backslash+asterisk packs folder contents.
    zip_file = WORK / "bench.zip"
    record(
        "ZIP (7-Zip)", zip_file,
        lambda: run([SEVENZIP, "a", "-tzip", "-mx5", "-bso0", str(zip_file), src_str + "\\*"]),
        lambda: run([SEVENZIP, "x", "-bso0", f"-o{WORK / 'out_zip'}", str(zip_file)]),
        WORK / "out_zip",
    )
    clean(zip_file)

    # 7z via 7-Zip (LZMA2, normal)
    sz_file = WORK / "bench.7z"
    record(
        "7z (7-Zip LZMA2)", sz_file,
        lambda: run([SEVENZIP, "a", "-t7z", "-mx5", "-bso0", str(sz_file), src_str + "\\*"]),
        lambda: run([SEVENZIP, "x", "-bso0", f"-o{WORK / 'out_7z'}", str(sz_file)]),
        WORK / "out_7z",
    )
    clean(sz_file)

    # RAR via WinRAR CLI (normal -m3). -r recurse, -ep1 strip base path, -idq quiet.
    rar_file = WORK / "bench.rar"
    record(
        "RAR (WinRAR)", rar_file,
        lambda: run([RAR, "a", "-m3", "-r", "-ep1", "-idq", str(rar_file), src_str + "\\*"]),
        lambda: run([RAR, "x", "-idq", str(rar_file), str(WORK / "out_rar") + "\\"]),
        WORK / "out_rar",
    )
    clean(rar_file)

    # tar.zst via bsdtar (same codec as UFZ, single stream)
    if TAR:
        zst_file = WORK / "bench.tar.zst"
        out = WORK / "out_zst"
        record(
            "tar.zst (bsdtar)", zst_file,
            lambda: run([TAR, "-c", "--zstd", "--options", "zstd:compression-level=6",
                         "-f", str(zst_file), "-C", src_str, "."]),
            lambda: run([TAR, "-x", "-f", str(zst_file), "-C", str(out)]),
            out,
        )
        clean(zst_file)

    RESULT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nResults saved: {RESULT_JSON}", flush=True)

    print("=" * 80)
    print(f"{'Format':<20}{'Pack(s)':>10}{'Unpack(s)':>10}{'Size(MB)':>12}{'Ratio':>9}{'Integ':>8}")
    print("-" * 80)
    for name, r in results["formats"].items():
        print(f"{name:<20}{r['pack_s']:>10.1f}{r['unpack_s']:>10.1f}"
              f"{r['size'] / 1048576:>12.1f}{r['ratio_pct']:>8.1f}%"
              f"{'PASS' if r['integrity'] else 'FAIL':>8}")
    print("=" * 80)


if __name__ == "__main__":
    main()
