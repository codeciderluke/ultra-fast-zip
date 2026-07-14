"""Ultra Fast Zip CLI — pack/unpack/inspect without the GUI.

Usage::

    python app/cli.py pack <folder> [-o out.ufz] [--block-size 8] [--level 6]
    python app/cli.py unpack <archive> [-o out_dir] [--threads 4] [--overwrite]
    python app/cli.py inspect <file.ufz> [--list]

``unpack`` auto-detects the format by magic bytes: .ufz plus zip, 7z, rar,
tar (gz/bz2/xz/zst), gz, bz2, xz, zst, cab, and iso.

Runs on the standard library only — no PySide6 required.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python app/cli.py` to import `app.*` when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Replace characters the console encoding (e.g. cp949) cannot represent
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

from app.core.archive import OperationCancelled, UfzError
from app.core.formats import extract_archive
from app.core.inspector import inspect
from app.core.packer import PackOptions, pack
from app.core.unpacker import UnpackOptions
from app.utils.format_utils import format_ratio, format_timestamp, human_size
from app.utils.path_utils import default_output_archive, default_output_folder

_LEVEL_TAGS = {"info": " ", "success": "+", "warning": "!", "error": "x"}


def _log(level: str, message: str) -> None:
    print(f"[{_LEVEL_TAGS.get(level, ' ')}] {message}", file=sys.stderr)


_current_file = [""]


def _status(name: str) -> None:
    _current_file[0] = name


def _progress(pct: int) -> None:
    name = _current_file[0]
    if len(name) > 46:
        name = "..." + name[-43:]
    bar = "#" * (pct // 4)
    sys.stderr.write(f"\r[{bar:<25}] {pct:3d}% {name:<46}")
    sys.stderr.flush()
    if pct >= 100:
        sys.stderr.write("\n")


def _quiet_callbacks(quiet: bool):
    if quiet:
        return (lambda pct: None), (lambda level, msg: None), (lambda name: None)
    return _progress, _log, _status


def cmd_pack(args: argparse.Namespace) -> int:
    src = Path(args.folder)
    out = Path(args.output) if args.output else default_output_archive(src)
    if out.exists() and not args.overwrite:
        _log("error", f"Output file already exists (use --overwrite): {out}")
        return 1

    options = PackOptions(
        block_size=args.block_size * 1024 * 1024,
        level=args.level,
        include_hidden=not args.no_hidden,
        include_empty_dirs=not args.no_empty_dirs,
        threads=args.threads,
    )
    progress_cb, log_cb, status_cb = _quiet_callbacks(args.quiet)
    result = pack(src, out, options, progress_cb=progress_cb, log_cb=log_cb, status_cb=status_cb)
    print(
        f"Done: {out} | {result.file_count:,} files, {result.block_count} blocks, "
        f"{human_size(result.total_size)} -> {human_size(result.compressed_size)} "
        f"({format_ratio(result.total_size, result.compressed_size)}), {result.elapsed:.1f}s"
    )
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    archive = Path(args.archive)
    out = Path(args.output) if args.output else default_output_folder(archive)

    options = UnpackOptions(threads=args.threads, overwrite=args.overwrite)
    progress_cb, log_cb, status_cb = _quiet_callbacks(args.quiet)
    result = extract_archive(archive, out, options,
                             progress_cb=progress_cb, log_cb=log_cb, status_cb=status_cb)
    print(
        f"Done: {out} | {result.file_count:,} files, "
        f"{human_size(result.total_size)}, {result.elapsed:.1f}s"
    )
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    info = inspect(Path(args.archive))
    print(f"Format version : {info.version}")
    print(f"Codec          : {info.codec}")
    print(f"Files          : {info.file_count:,}")
    print(f"Blocks         : {info.block_count:,}")
    print(f"Original size  : {human_size(info.total_size)} ({info.total_size:,} B)")
    print(f"Packed size    : {human_size(info.compressed_size)} ({info.compressed_size:,} B)")
    print(f"Ratio          : {format_ratio(info.total_size, info.compressed_size)}")
    print(f"Created        : {format_timestamp(info.created)}")
    print(f"Block size     : {human_size(info.block_size)}")
    if args.list:
        print()
        for entry in info.files:
            print(f"{human_size(entry.size):>10}  {entry.path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ufz",
        description="Ultra Fast Zip archive CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_pack = sub.add_parser("pack", help="compress a folder into a .ufz archive")
    p_pack.add_argument("folder", help="folder to compress")
    p_pack.add_argument("-o", "--output", help="output .ufz path (default: <folder>.ufz)")
    p_pack.add_argument(
        "--block-size", type=int, default=8, choices=[1, 4, 8, 16, 32],
        metavar="MB", help="block size in MB (default: 8)",
    )
    p_pack.add_argument(
        "--level", type=int, default=6, choices=range(1, 23),
        metavar="1-22", help="Zstandard level (default: 6)",
    )
    p_pack.add_argument(
        "-t", "--threads", type=int, default=0,
        help="compress worker threads (default: 0 = CPU count)",
    )
    p_pack.add_argument("--no-hidden", action="store_true", help="exclude hidden files")
    p_pack.add_argument("--no-empty-dirs", action="store_true", help="exclude empty folders")
    p_pack.add_argument("--overwrite", action="store_true", help="overwrite existing output file")
    p_pack.add_argument("-q", "--quiet", action="store_true", help="suppress progress and logs")
    p_pack.set_defaults(func=cmd_pack)

    p_unpack = sub.add_parser(
        "unpack", help="extract an archive (auto-detects ufz/zip/7z/rar/tar/gz/cab/iso/...)"
    )
    p_unpack.add_argument("archive", help="archive to extract (format auto-detected)")
    p_unpack.add_argument("-o", "--output", help="output folder (default: <name>_extracted)")
    p_unpack.add_argument(
        "-t", "--threads", type=int, default=0,
        help="worker threads (.ufz only, default: 0 = CPU count)",
    )
    p_unpack.add_argument("--overwrite", action="store_true", help="overwrite existing files")
    p_unpack.add_argument("-q", "--quiet", action="store_true", help="suppress progress and logs")
    p_unpack.set_defaults(func=cmd_unpack)

    p_inspect = sub.add_parser("inspect", help="show .ufz archive info")
    p_inspect.add_argument("archive", help=".ufz file to inspect")
    p_inspect.add_argument("-l", "--list", action="store_true", help="list files")
    p_inspect.set_defaults(func=cmd_inspect)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None and len(sys.argv) == 1:
        # No args (usually a double-click): show help; in a frozen build,
        # keep the console window open.
        parser.print_help()
        if getattr(sys, "frozen", False):
            print()
            try:
                input("ufz is a command-line tool. Press Enter to close...")
            except EOFError:
                pass
        return 0
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except OperationCancelled:
        _log("warning", "Operation cancelled.")
        return 130
    except KeyboardInterrupt:
        _log("warning", "Interrupted (Ctrl+C)")
        return 130
    except (UfzError, OSError, ValueError) as exc:
        _log("error", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
