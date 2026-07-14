"""Pipelined parallel extraction of ``.ufz`` archives.

Producer/consumer pipeline::

    Archive (mmap, zero-copy reads)
        v
    Block Queue            <- block map built from metadata, disk-friendly order
        v
    Decompress Workers x N <- checksum verify + Zstandard decompress (GIL released)
        v   (backpressure via 256MB in-flight memory budget)
    Write Queue
        v
    Writer Workers x N     <- per-file checksum verify + write
        v
    Disk

Reading, decompression, and writing overlap so CPU and disk never wait
on each other.
"""
from __future__ import annotations

import mmap
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import zstandard

from app.core.archive import (
    CODEC_ZLIB,
    CODEC_ZSTD,
    CorruptArchiveError,
    OperationCancelled,
    decompress_block,
    digest,
    iter_block_locations,
    read_metadata,
)
from app.core.models import FileEntry
from app.utils.path_utils import safe_join

ProgressCallback = Callable[[int], None]
LogCallback = Callable[[str, str], None]
StatusCallback = Callable[[str], None]  # relative path currently being written

# Minimum interval between status callbacks — avoids flooding GUI signals
_STATUS_INTERVAL = 0.05

# Total decompressed bytes allowed in memory at once (backpressure)
_INFLIGHT_MEMORY_BUDGET = 256 * 1024 * 1024


@dataclass
class UnpackOptions:
    threads: int = 0  # 0 = auto (CPU count); spawns this many decompress AND write workers
    overwrite: bool = False


@dataclass
class UnpackResult:
    file_count: int
    block_count: int
    total_size: int
    elapsed: float


def _resolve_threads(threads: int) -> int:
    if threads and threads > 0:
        return threads
    return max(1, os.cpu_count() or 1)


def unpack(
    archive_path: Path,
    out_dir: Path,
    options: Optional[UnpackOptions] = None,
    progress_cb: Optional[ProgressCallback] = None,
    log_cb: Optional[LogCallback] = None,
    cancel: Optional[threading.Event] = None,
    status_cb: Optional[StatusCallback] = None,
) -> UnpackResult:
    """Extract ``archive_path`` into ``out_dir`` using the parallel pipeline."""
    options = options or UnpackOptions()
    log = log_cb or (lambda level, msg: None)
    report = progress_cb or (lambda pct: None)
    status = status_cb or (lambda name: None)
    cancel = cancel or threading.Event()
    started = time.monotonic()

    archive_path = Path(archive_path)
    out_dir = Path(out_dir)
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive does not exist: {archive_path}")

    # ------------------------------------------------------------------ index
    with open(archive_path, "rb") as fp:
        metadata = read_metadata(fp)
        version = int(metadata.get("version", 1))
        codec = str(metadata.get("codec", CODEC_ZLIB))
        block_count = int(metadata.get("block_count", 0))
        locations = list(iter_block_locations(fp, block_count, version))

    entries = [FileEntry.from_dict(item) for item in metadata.get("files", [])]
    dirs = list(metadata.get("dirs", []))
    total_size = sum(entry.size for entry in entries)

    # Validate every path up front and cache targets (path traversal guard).
    targets: dict[str, Path] = {entry.path: safe_join(out_dir, entry.path) for entry in entries}

    # Create all directories once so the write stage only writes files.
    out_dir.mkdir(parents=True, exist_ok=True)
    dir_paths = {target.parent for target in targets.values()}
    dir_paths.update(safe_join(out_dir, rel) for rel in dirs)
    for dir_path in sorted(dir_paths, key=lambda p: len(p.parts)):
        dir_path.mkdir(parents=True, exist_ok=True)

    # Zero-length files carry no block data — create them directly.
    by_block: dict[int, list[FileEntry]] = {}
    for entry in entries:
        target = targets[entry.path]
        if entry.length == 0:
            try:
                with open(target, "wb" if options.overwrite else "xb"):
                    pass
            except FileExistsError:
                raise FileExistsError(
                    f"File already exists (overwrite disabled): {entry.path}"
                ) from None
            try:
                os.utime(target, (entry.mtime, entry.mtime))
            except OSError:
                pass
        else:
            by_block.setdefault(entry.block, []).append(entry)

    thread_count = _resolve_threads(options.threads)
    log(
        "info",
        f"Extracting: {len(entries):,} files, {block_count} blocks, "
        f"{thread_count} decompress + {thread_count} write workers (pipeline)",
    )

    # --------------------------------------------------------------- pipeline
    errors: list[BaseException] = []
    error_lock = threading.Lock()

    def fail(exc: BaseException) -> None:
        # Traceback frames holding mmap slices would keep the mmap open
        exc.__traceback__ = None
        with error_lock:
            errors.append(exc)
        cancel.set()

    # Pre-filled in sequential (disk-friendly) order; FIFO doubles as load balancing
    block_queue: queue.Queue = queue.Queue()
    for index, location in enumerate(locations):
        block_queue.put((index, location))

    # Cap decompressed blocks held in memory before they are written out
    max_raw = max([raw_size for _, raw_size, _, _ in locations], default=1)
    max_inflight = max(2, min(thread_count * 2, _INFLIGHT_MEMORY_BUDGET // max(1, max_raw)))
    inflight = threading.Semaphore(max_inflight)

    write_queue: queue.Queue = queue.Queue()

    done_blocks = 0
    progress_lock = threading.Lock()
    log_step = max(1, block_count // 20)

    def on_block_done(index: int, file_count: int) -> None:
        nonlocal done_blocks
        with progress_lock:
            done_blocks += 1
            current = done_blocks
        if block_count > 0:
            report(int(current / block_count * 100))
        if current % log_step == 0 or current == block_count:
            log("info", f"Blocks {current}/{block_count} done")

    def acquire_inflight() -> bool:
        while not cancel.is_set():
            if inflight.acquire(timeout=0.2):
                return True
        return False

    def decompress_worker(view: memoryview) -> None:
        decompressor = zstandard.ZstdDecompressor() if codec == CODEC_ZSTD else None
        compressed = None
        try:
            while not cancel.is_set():
                try:
                    index, (offset, raw_size, comp_size, block_digest) = block_queue.get_nowait()
                except queue.Empty:
                    return
                compressed = view[offset : offset + comp_size]
                if not acquire_inflight():
                    return
                try:
                    raw = decompress_block(
                        compressed, raw_size, block_digest, codec, version, decompressor
                    )
                except BaseException:
                    inflight.release()
                    raise
                write_queue.put((index, raw))
        except BaseException as exc:  # noqa: BLE001 — abort the whole pipeline
            fail(exc)
        finally:
            # Release the mmap slice so the mmap can be closed
            del compressed

    # Shared status timestamp across writers (race is harmless — rate limiting only)
    status_state = [0.0]

    def maybe_status(name: str) -> None:
        now = time.monotonic()
        if now - status_state[0] >= _STATUS_INTERVAL:
            status_state[0] = now
            status(name)

    def writer_worker() -> None:
        while True:
            item = write_queue.get()
            if item is None:
                return
            index, raw = item
            try:
                if cancel.is_set():
                    continue
                raw_view = memoryview(raw)
                block_files = by_block.get(index, [])
                mode = "wb" if options.overwrite else "xb"
                for entry in block_files:
                    if cancel.is_set():
                        raise OperationCancelled("Cancelled by user.")
                    maybe_status(entry.path)
                    target = targets[entry.path]
                    data = raw_view[entry.offset : entry.offset + entry.length]
                    if len(data) != entry.length:
                        raise CorruptArchiveError(f"File data range is invalid: {entry.path}")
                    if digest(data, version) != entry.checksum:
                        raise CorruptArchiveError(f"Checksum mismatch: {entry.path}")
                    try:
                        # Exclusive create ("xb") replaces an existence-check stat
                        with open(target, mode) as out_fp:
                            out_fp.write(data)
                    except FileExistsError:
                        raise FileExistsError(
                            f"File already exists (overwrite disabled): {entry.path}"
                        ) from None
                    try:
                        os.utime(target, (entry.mtime, entry.mtime))
                        if os.name == "posix":
                            os.chmod(target, entry.mode)
                    except OSError:
                        pass
                on_block_done(index, len(block_files))
            except BaseException as exc:  # noqa: BLE001 — abort the whole pipeline
                fail(exc)
            finally:
                inflight.release()

    with open(archive_path, "rb") as fp:
        mm = mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ)
        view = memoryview(mm)
        try:
            decompress_threads = [
                threading.Thread(target=decompress_worker, args=(view,), daemon=True)
                for _ in range(thread_count)
            ]
            writer_threads = [
                threading.Thread(target=writer_worker, daemon=True)
                for _ in range(thread_count)
            ]
            for thread in decompress_threads + writer_threads:
                thread.start()
            for thread in decompress_threads:
                thread.join()
            for _ in writer_threads:
                write_queue.put(None)
            for thread in writer_threads:
                thread.join()
        finally:
            view.release()
            mm.close()

    if errors:
        real = [exc for exc in errors if not isinstance(exc, OperationCancelled)]
        raise (real[0] if real else errors[0])
    if cancel.is_set():
        raise OperationCancelled("Cancelled by user.")

    report(100)
    elapsed = time.monotonic() - started
    log("success", f"Extracted {len(entries):,} files -> {out_dir}")
    return UnpackResult(
        file_count=len(entries),
        block_count=block_count,
        total_size=total_size,
        elapsed=elapsed,
    )
