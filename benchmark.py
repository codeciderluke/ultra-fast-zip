"""UFZ vs ZIP compression/extraction benchmark.

Usage::

    python benchmark.py <target folder> [--work-dir DIR] [--level 6] [--block-size 8]
                        [--quick] [--keep]

Compares pack/unpack time, archive size, and ratio, then verifies that the
restored tree matches the source.

- ``--quick``: compare file count + size only, instead of full CRC32
- ``--keep``: keep benchmark outputs (archives, extracted folders)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

from app.core.packer import PackOptions, pack
from app.core.unpacker import UnpackOptions, unpack

_CHUNK = 4 * 1024 * 1024


def snapshot(root: Path, with_crc: bool) -> dict:
    """rel_path -> (size, crc32|None), used for integrity comparison."""
    result = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full = Path(dirpath) / name
            if with_crc:
                crc = 0
                size = 0
                with open(full, "rb") as fp:
                    while True:
                        chunk = fp.read(_CHUNK)
                        if not chunk:
                            break
                        crc = zlib.crc32(chunk, crc)
                        size += len(chunk)
                value = (size, crc & 0xFFFFFFFF)
            else:
                value = (full.stat().st_size, None)
            result[full.relative_to(root).as_posix()] = value
    return result


def timed(label: str, fn) -> float:
    t0 = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t0
    print(f"  {label}: {elapsed:.1f}s", flush=True)
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description="UFZ vs ZIP benchmark")
    parser.add_argument("folder", help="target folder to benchmark")
    parser.add_argument("--work-dir", help="output folder (default: <target>_bench)")
    parser.add_argument("--level", type=int, default=6, help="compression level (default 6, both sides)")
    parser.add_argument("--block-size", type=int, default=8, help="UFZ block size in MB (default 8)")
    parser.add_argument("--quick", action="store_true", help="integrity check by count+size only")
    parser.add_argument("--keep", action="store_true", help="keep benchmark outputs")
    args = parser.parse_args()

    src = Path(args.folder)
    if not src.is_dir():
        print(f"Folder does not exist: {src}", file=sys.stderr)
        return 1

    work = Path(args.work_dir) if args.work_dir else src.parent / f"{src.name}_bench"
    ufz_file = work / "bench.ufz"
    zip_file = work / "bench.zip"
    ufz_out = work / "ufz_extracted"
    zip_out = work / "zip_extracted"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    with_crc = not args.quick
    mode = "full CRC32 comparison" if with_crc else "count+size comparison (--quick)"
    print(f"[1/6] Snapshotting source ({mode})...", flush=True)
    t0 = time.perf_counter()
    src_snap = snapshot(src, with_crc)
    total_bytes = sum(size for size, _ in src_snap.values())
    print(f"  {len(src_snap):,} files, {total_bytes / 1048576:.1f} MB "
          f"({time.perf_counter() - t0:.1f}s)", flush=True)

    print(f"[2/6] UFZ pack (level {args.level}, block {args.block_size}MB)...", flush=True)
    ufz_pack_s = timed("ufz pack", lambda: pack(
        src, ufz_file, PackOptions(block_size=args.block_size * 1024 * 1024, level=args.level)))

    print("[3/6] UFZ unpack (auto threads)...", flush=True)
    ufz_unpack_s = timed("ufz unpack", lambda: unpack(ufz_file, ufz_out, UnpackOptions(threads=0)))

    print(f"[4/6] ZIP pack (deflate level {args.level})...", flush=True)

    def zip_create() -> None:
        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED, compresslevel=args.level) as zf:
            for dirpath, _, filenames in os.walk(src):
                for name in filenames:
                    full = Path(dirpath) / name
                    zf.write(full, full.relative_to(src).as_posix())

    zip_pack_s = timed("zip pack", zip_create)

    print("[5/6] ZIP unpack...", flush=True)

    def zip_extract() -> None:
        with zipfile.ZipFile(zip_file) as zf:
            zf.extractall(zip_out)

    zip_unpack_s = timed("zip unpack", zip_extract)

    print("[6/6] Integrity check...", flush=True)
    ufz_ok = snapshot(ufz_out, with_crc) == src_snap
    zip_ok = snapshot(zip_out, with_crc) == src_snap
    print(f"  UFZ restore match: {ufz_ok}", flush=True)
    print(f"  ZIP restore match: {zip_ok}", flush=True)

    ufz_size = ufz_file.stat().st_size
    zip_size = zip_file.stat().st_size

    print()
    print("=" * 68)
    print(f"Source: {len(src_snap):,} files, {total_bytes / 1048576:.1f} MB — {src}")
    print(f"{'Metric':<14}{'UFZ':>16}{'ZIP':>16}{'ZIP/UFZ':>16}")
    print("-" * 68)
    print(f"{'Pack time':<14}{ufz_pack_s:>15.1f}s{zip_pack_s:>15.1f}s{zip_pack_s / ufz_pack_s:>15.2f}x")
    print(f"{'Unpack time':<14}{ufz_unpack_s:>15.1f}s{zip_unpack_s:>15.1f}s{zip_unpack_s / ufz_unpack_s:>15.2f}x")
    print(f"{'Size':<14}{ufz_size / 1048576:>13.1f} MB{zip_size / 1048576:>13.1f} MB{zip_size / ufz_size:>15.2f}x")
    print(f"{'Ratio':<14}{ufz_size / total_bytes * 100:>15.1f}%{zip_size / total_bytes * 100:>15.1f}%")
    print(f"{'Integrity':<14}{'PASS' if ufz_ok else 'FAIL':>16}{'PASS' if zip_ok else 'FAIL':>16}")
    print("=" * 68)

    if args.keep:
        print(f"Outputs kept: {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
        print("Outputs cleaned up.")

    return 0 if (ufz_ok and zip_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
