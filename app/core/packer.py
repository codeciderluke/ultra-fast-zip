"""Scan a folder, group files into blocks, compress into a .ufz archive."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.core.archive import (
    DEFAULT_CODEC,
    FORMAT_VERSION,
    OperationCancelled,
    make_compressor,
    new_hasher,
    write_block,
    write_header,
)
from app.core.models import FileEntry
from app.utils.path_utils import is_hidden

ProgressCallback = Callable[[int], None]
LogCallback = Callable[[str, str], None]
StatusCallback = Callable[[str], None]  # relative path currently being processed

# Minimum interval between status callbacks — avoids flooding GUI signals
_STATUS_INTERVAL = 0.05

_READ_CHUNK = 4 * 1024 * 1024

DEFAULT_BLOCK_SIZE = 8 * 1024 * 1024
DEFAULT_LEVEL = 6


@dataclass
class PackOptions:
    block_size: int = DEFAULT_BLOCK_SIZE
    level: int = DEFAULT_LEVEL
    include_hidden: bool = True
    include_empty_dirs: bool = True


@dataclass
class PackResult:
    file_count: int
    block_count: int
    total_size: int
    compressed_size: int
    elapsed: float


def scan_folder(
    src_dir: Path, options: PackOptions
) -> tuple[list[tuple[str, str, int, int, int]], list[str]]:
    """Scan a folder; return (abs_path, rel_path, size, mtime, mode) tuples
    plus a list of empty directories.

    Uses plain string paths instead of pathlib to stay fast on tens of
    thousands of files.
    """
    files: list[tuple[str, str, int, int, int]] = []
    empty_dirs: list[str] = []
    src_str = os.path.normpath(str(src_dir))
    prefix_len = len(src_str) + 1

    for root, dirnames, filenames in os.walk(src_str):
        if not options.include_hidden:
            dirnames[:] = [d for d in dirnames if not is_hidden(os.path.join(root, d))]
            filenames = [f for f in filenames if not is_hidden(os.path.join(root, f))]
        dirnames.sort()
        filenames.sort()

        rel_root = root[prefix_len:].replace(os.sep, "/")

        if options.include_empty_dirs and not dirnames and not filenames and rel_root:
            empty_dirs.append(rel_root)

        for name in filenames:
            full = os.path.join(root, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = f"{rel_root}/{name}" if rel_root else name
            files.append((full, rel, st.st_size, int(st.st_mtime), st.st_mode & 0o7777))
    return files, empty_dirs


def pack(
    src_dir: Path,
    out_path: Path,
    options: Optional[PackOptions] = None,
    progress_cb: Optional[ProgressCallback] = None,
    log_cb: Optional[LogCallback] = None,
    cancel: Optional[threading.Event] = None,
    status_cb: Optional[StatusCallback] = None,
) -> PackResult:
    """Compress ``src_dir`` into the ``out_path`` .ufz archive.

    Progress: 0-90% = reading + block compression (by bytes),
    90-100% = archive assembly.
    """
    options = options or PackOptions()
    log = log_cb or (lambda level, msg: None)
    report = progress_cb or (lambda pct: None)
    status = status_cb or (lambda name: None)
    cancel = cancel or threading.Event()
    started = time.monotonic()

    src_dir = Path(src_dir)
    out_path = Path(out_path)
    if not src_dir.is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {src_dir}")

    log("info", f"Scanning folder: {src_dir}")
    files, empty_dirs = scan_folder(src_dir, options)
    total_bytes = sum(size for _, _, size, _, _ in files)
    log("info", f"Found {len(files):,} files, {total_bytes:,} bytes total")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_blocks = out_path.with_name(out_path.name + ".blocks.tmp")

    entries: list[FileEntry] = []
    block_index = 0
    compressed_total = 0
    processed_bytes = 0
    last_pct = -1
    last_status = 0.0

    def report_bytes() -> None:
        nonlocal last_pct
        if total_bytes > 0:
            pct = int(processed_bytes / total_bytes * 90)
            if pct != last_pct:
                last_pct = pct
                report(min(pct, 90))

    compressor = make_compressor(options.level)

    def flush_block(fp, buffer: bytearray) -> None:
        nonlocal block_index, compressed_total
        if not buffer:
            return
        compressed_total += write_block(fp, bytes(buffer), options.level, compressor)
        block_index += 1
        buffer.clear()

    try:
        with open(tmp_blocks, "wb") as bfp:
            buffer = bytearray()
            for full, rel, size, mtime, mode in files:
                if cancel.is_set():
                    raise OperationCancelled("Cancelled by user.")

                now = time.monotonic()
                if now - last_status >= _STATUS_INTERVAL:
                    last_status = now
                    status(rel)

                offset = len(buffer)
                hasher = new_hasher()
                try:
                    # Buffered read(n) preallocates n bytes, which is very slow
                    # for many small files — only ever request the remaining size.
                    with open(full, "rb") as src:
                        if size <= _READ_CHUNK:
                            data = src.read()
                            hasher.update(data)
                            buffer.extend(data)
                            processed_bytes += len(data)
                            del data
                        else:
                            remaining = size
                            while remaining > 0:
                                chunk = src.read(min(_READ_CHUNK, remaining))
                                if not chunk:
                                    break
                                remaining -= len(chunk)
                                hasher.update(chunk)
                                buffer.extend(chunk)
                                processed_bytes += len(chunk)
                                report_bytes()
                except OSError as exc:
                    raise OSError(f"Cannot read file: {full} ({exc})") from exc

                actual_length = len(buffer) - offset
                entries.append(
                    FileEntry(
                        path=rel,
                        size=actual_length,
                        mtime=mtime,
                        mode=mode,
                        block=block_index,
                        offset=offset,
                        length=actual_length,
                        checksum=hasher.intdigest(),
                    )
                )

                if len(buffer) >= options.block_size:
                    flush_block(bfp, buffer)

                report_bytes()

            flush_block(bfp, buffer)

        metadata = {
            "format": "UFZ",
            "version": FORMAT_VERSION,
            "codec": DEFAULT_CODEC,
            "checksum": "xxh64",
            "created": int(time.time()),
            "block_size": options.block_size,
            "file_count": len(entries),
            "block_count": block_index,
            "dirs": empty_dirs,
            "files": [entry.to_dict() for entry in entries],
        }

        log("info", f"Compressed {block_index} blocks, assembling archive...")
        status("Assembling archive...")
        copy_total = max(1, tmp_blocks.stat().st_size)
        copied = 0
        with open(out_path, "wb") as out_fp:
            write_header(out_fp, metadata)
            with open(tmp_blocks, "rb") as bfp:
                while True:
                    chunk = bfp.read(_READ_CHUNK)
                    if not chunk:
                        break
                    out_fp.write(chunk)
                    copied += len(chunk)
                    report(90 + int(copied / copy_total * 10))
    except BaseException:
        # Clean up partial output on failure or cancellation
        for leftover in (tmp_blocks, out_path):
            try:
                if leftover.exists():
                    leftover.unlink()
            except OSError:
                pass
        raise
    finally:
        try:
            if tmp_blocks.exists():
                tmp_blocks.unlink()
        except OSError:
            pass

    report(100)
    elapsed = time.monotonic() - started
    archive_size = out_path.stat().st_size
    log(
        "success",
        f"Packed: {out_path.name} — {total_bytes:,} B -> {archive_size:,} B "
        f"({archive_size / total_bytes * 100:.1f}%)" if total_bytes else f"Packed: {out_path.name}",
    )
    return PackResult(
        file_count=len(entries),
        block_count=block_index,
        total_size=total_bytes,
        compressed_size=archive_size,
        elapsed=elapsed,
    )
