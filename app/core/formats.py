"""Archive format auto-detection and multi-format extraction.

UFZ is the native format. Other common archive types are detected by magic
bytes and extracted with the best available backend:

- zip                      : stdlib ``zipfile``
- tar / tar.gz/bz2/xz/zst  : stdlib ``tarfile`` (+ zstandard stream for zst)
- gz / bz2 / xz / zst      : single-file stream decompression
- 7z                       : ``py7zr`` if installed, else bsdtar
- rar / cab / iso          : bsdtar (libarchive — bundled with Windows 10+/macOS)

All extractors share the UFZ callback signature (progress/log/status/cancel)
so the GUI and CLI use them identically.
"""
from __future__ import annotations

import bz2
import gzip
import lzma
import os
import posixpath
import shutil
import subprocess
import tarfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import zstandard

from app.core.archive import LEGACY_MAGIC, MAGIC, OperationCancelled, UfzError
from app.core.unpacker import UnpackOptions, UnpackResult, unpack
from app.utils.path_utils import safe_join

ProgressCallback = Callable[[int], None]
LogCallback = Callable[[str, str], None]
StatusCallback = Callable[[str], None]

_CHUNK = 4 * 1024 * 1024

# Formats delegated to bsdtar when no Python backend exists
_BSDTAR_FORMATS = frozenset({"rar", "cab", "iso", "7z"})

FORMAT_LABELS = {
    "ufz": "UFZ",
    "zip": "ZIP",
    "7z": "7-Zip",
    "rar": "RAR",
    "cab": "CAB",
    "iso": "ISO",
    "tar": "TAR",
    "tar.gz": "TAR+GZIP",
    "tar.bz2": "TAR+BZIP2",
    "tar.xz": "TAR+XZ",
    "tar.zst": "TAR+ZSTD",
    "gz": "GZIP",
    "bz2": "BZIP2",
    "xz": "XZ",
    "zst": "ZSTD",
}

# Extensions for GUI file dialog filters
SUPPORTED_PATTERNS = (
    "*.ufz *.fpk *.zip *.7z *.rar *.tar *.tar.gz *.tgz *.tar.bz2 *.tbz2 "
    "*.tar.xz *.txz *.tar.zst *.gz *.bz2 *.xz *.zst *.cab *.iso"
)


class UnsupportedFormatError(UfzError):
    """The file is not a recognized archive format."""


@dataclass
class _Callbacks:
    report: ProgressCallback
    log: LogCallback
    status: StatusCallback
    cancel: threading.Event


def _tar_peek_is_tar(data: bytes, path: Path) -> bool:
    """True if decompressed head looks like tar, or the filename says so."""
    if len(data) >= 262 and data[257:262] == b"ustar":
        return True
    name = path.name.lower()
    return name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                          ".tar.xz", ".txz", ".tar.zst", ".tar"))


def _peek_decompressed(path: Path, codec: str, n: int = 600) -> bytes:
    try:
        if codec == "gz":
            with gzip.open(path, "rb") as fp:
                return fp.read(n)
        if codec == "bz2":
            with bz2.open(path, "rb") as fp:
                return fp.read(n)
        if codec == "xz":
            with lzma.open(path, "rb") as fp:
                return fp.read(n)
        if codec == "zst":
            with open(path, "rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw) as fp:
                    return fp.read(n)
    except (OSError, EOFError, lzma.LZMAError, zstandard.ZstdError):
        return b""
    return b""


def detect_format(path: Path) -> Optional[str]:
    """Detect the archive format by magic bytes (extension as tiebreaker).

    Returns a key of :data:`FORMAT_LABELS`, or ``None`` if unrecognized.
    """
    path = Path(path)
    try:
        with open(path, "rb") as fp:
            head = fp.read(512)
            fp.seek(32769)
            iso_sig = fp.read(5)
    except OSError:
        return None
    if len(head) < 4:
        return None

    if head[:8] in (MAGIC, LEGACY_MAGIC):
        return "ufz"
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    if head[:4] == b"Rar!":
        return "rar"
    if head[:4] == b"MSCF":
        return "cab"
    if head[:2] == b"\x1f\x8b":
        return "tar.gz" if _tar_peek_is_tar(_peek_decompressed(path, "gz"), path) else "gz"
    if head[:3] == b"BZh":
        return "tar.bz2" if _tar_peek_is_tar(_peek_decompressed(path, "bz2"), path) else "bz2"
    if head[:6] == b"\xfd7zXZ\x00":
        return "tar.xz" if _tar_peek_is_tar(_peek_decompressed(path, "xz"), path) else "xz"
    if head[:4] == b"\x28\xb5\x2f\xfd":
        return "tar.zst" if _tar_peek_is_tar(_peek_decompressed(path, "zst"), path) else "zst"
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar"
    if iso_sig == b"CD001":
        return "iso"
    # Pre-POSIX tar has no magic — trust the extension
    if path.suffix.lower() == ".tar":
        return "tar"
    return None


def _check_target(target: Path, rel: str, overwrite: bool) -> None:
    if not overwrite and target.exists():
        raise FileExistsError(f"File already exists (overwrite disabled): {rel}")


def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    """Recover cp949 names from zips without the UTF-8 flag; normalize './'."""
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("cp949")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return posixpath.normpath(name)


def _extract_zip(path: Path, out_dir: Path, overwrite: bool, cb: _Callbacks) -> tuple[int, int]:
    with zipfile.ZipFile(path) as zf:
        infos = [i for i in zf.infolist()
                 if not i.is_dir() and _fix_zip_name(i) not in (".", "")]
        names = {id(i): _fix_zip_name(i) for i in infos}
        total = sum(i.file_size for i in infos) or 1
        # Validate every path before writing anything
        targets = {id(i): safe_join(out_dir, names[id(i)]) for i in infos}
        for info in zf.infolist():
            if info.is_dir() and _fix_zip_name(info) not in (".", ""):
                safe_join(out_dir, _fix_zip_name(info)).mkdir(parents=True, exist_ok=True)

        done = 0
        for info in infos:
            if cb.cancel.is_set():
                raise OperationCancelled("Cancelled by user.")
            rel = names[id(info)]
            target = targets[id(info)]
            _check_target(target, rel, overwrite)
            cb.status(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, _CHUNK)
            mtime = time.mktime(info.date_time + (0, 0, -1))
            try:
                os.utime(target, (mtime, mtime))
            except (OSError, OverflowError, ValueError):
                pass
            done += info.file_size
            cb.report(int(done / total * 100))
        return len(infos), sum(i.file_size for i in infos)


def _extract_tar(path: Path, out_dir: Path, fmt: str, overwrite: bool,
                 cb: _Callbacks) -> tuple[int, int]:
    size = path.stat().st_size or 1
    raw = open(path, "rb")

    class _Track:
        """File wrapper reporting progress from the compressed read offset."""

        def read(self, n=-1):
            data = raw.read(n)
            cb.report(min(99, int(raw.tell() / size * 100)))
            return data

        def __getattr__(self, name):
            return getattr(raw, name)

    try:
        if fmt == "tar.zst":
            stream = zstandard.ZstdDecompressor().stream_reader(_Track())
            tf = tarfile.open(fileobj=stream, mode="r|")
        else:
            tf = tarfile.open(fileobj=_Track(), mode="r|*")
        count = 0
        total = 0
        with tf:
            for member in tf:
                if cb.cancel.is_set():
                    raise OperationCancelled("Cancelled by user.")
                # Normalize "./name" entries produced by bsdtar and friends
                rel = posixpath.normpath(member.name)
                if rel in (".", ""):
                    continue
                target = safe_join(out_dir, rel)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    cb.log("warning", f"Skipping non-regular file: {rel}")
                    continue
                _check_target(target, rel, overwrite)
                cb.status(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    continue
                with src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, _CHUNK)
                try:
                    os.utime(target, (member.mtime, member.mtime))
                except OSError:
                    pass
                count += 1
                total += member.size
        return count, total
    finally:
        raw.close()


def _strip_archive_suffix(path: Path) -> str:
    name = path.name
    lower = name.lower()
    for suffix in (".gz", ".bz2", ".xz", ".zst"):
        if lower.endswith(suffix):
            return name[: -len(suffix)] or name
    return path.stem


def _extract_single(path: Path, out_dir: Path, fmt: str, overwrite: bool,
                    cb: _Callbacks) -> tuple[int, int]:
    """Decompress a single-file stream (foo.txt.gz -> out_dir/foo.txt)."""
    rel = _strip_archive_suffix(path)
    target = safe_join(out_dir, rel)
    _check_target(target, rel, overwrite)
    out_dir.mkdir(parents=True, exist_ok=True)
    cb.status(rel)
    size = path.stat().st_size or 1
    written = 0
    with open(path, "rb") as raw:
        openers = {
            "gz": lambda: gzip.GzipFile(fileobj=raw),
            "bz2": lambda: bz2.BZ2File(raw),
            "xz": lambda: lzma.LZMAFile(raw),
            "zst": lambda: zstandard.ZstdDecompressor().stream_reader(raw),
        }
        with openers[fmt]() as src, open(target, "wb") as dst:
            while True:
                if cb.cancel.is_set():
                    raise OperationCancelled("Cancelled by user.")
                chunk = src.read(_CHUNK)
                if not chunk:
                    break
                dst.write(chunk)
                written += len(chunk)
                # Progress from the compressed read offset
                cb.report(min(99, int(raw.tell() / size * 100)))
    cb.report(100)
    return 1, written


def _extract_7z_py7zr(path: Path, out_dir: Path, overwrite: bool, cb: _Callbacks) -> tuple[int, int]:
    import py7zr

    with py7zr.SevenZipFile(path, mode="r") as zf:
        names = zf.getnames()
        # Validate all paths; py7zr also guards traversal, this is defense in depth
        for rel in names:
            safe_join(out_dir, rel)
        if not overwrite:
            for rel in names:
                _check_target(safe_join(out_dir, rel), rel, overwrite)
        cb.status(path.name)
        zf.extractall(out_dir)
    total = sum((out_dir / rel).stat().st_size
                for rel in names if (out_dir / rel).is_file())
    cb.report(100)
    return len(names), total


def _extract_bsdtar(path: Path, out_dir: Path, fmt: str, overwrite: bool,
                    cb: _Callbacks) -> tuple[int, int]:
    tar_exe = shutil.which("tar")
    if not tar_exe:
        raise UnsupportedFormatError(
            f"Extracting {FORMAT_LABELS.get(fmt, fmt)} requires bsdtar "
            "(bundled with Windows 10+/macOS; not found on this system)."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cb.log("info", f"Delegating {FORMAT_LABELS.get(fmt, fmt)} extraction to bsdtar (no progress reporting).")
    cb.status(path.name)
    args = [tar_exe, "-x"]
    if not overwrite:
        args.append("-k")  # keep existing files (skip instead of overwrite)
    args += ["-f", str(path), "-C", str(out_dir)]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while proc.poll() is None:
        if cb.cancel.is_set():
            proc.kill()
            raise OperationCancelled("Cancelled by user.")
        time.sleep(0.1)
    if proc.returncode != 0:
        stderr = (proc.stderr.read() if proc.stderr else "")[:500]
        raise UfzError(f"bsdtar extraction failed (exit {proc.returncode}): {stderr}")
    count = 0
    total = 0
    for dirpath, _, filenames in os.walk(out_dir):
        for name in filenames:
            count += 1
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    cb.report(100)
    return count, total


def extract_archive(
    archive_path: Path,
    out_dir: Path,
    options: Optional[UnpackOptions] = None,
    progress_cb: Optional[ProgressCallback] = None,
    log_cb: Optional[LogCallback] = None,
    cancel: Optional[threading.Event] = None,
    status_cb: Optional[StatusCallback] = None,
) -> UnpackResult:
    """Extract any supported archive into ``out_dir``.

    UFZ archives use the native parallel pipeline; other formats are detected
    by magic bytes and routed to the matching backend. ``options.threads``
    only affects UFZ.
    """
    options = options or UnpackOptions()
    archive_path = Path(archive_path)
    out_dir = Path(out_dir)
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive does not exist: {archive_path}")

    fmt = detect_format(archive_path)
    if fmt is None:
        raise UnsupportedFormatError(
            f"Unsupported or unrecognized archive format: {archive_path.name}"
        )
    if fmt == "ufz":
        return unpack(archive_path, out_dir, options,
                      progress_cb=progress_cb, log_cb=log_cb,
                      cancel=cancel, status_cb=status_cb)

    cb = _Callbacks(
        report=progress_cb or (lambda pct: None),
        log=log_cb or (lambda level, msg: None),
        status=status_cb or (lambda name: None),
        cancel=cancel or threading.Event(),
    )
    started = time.monotonic()
    cb.log("info", f"Detected {FORMAT_LABELS[fmt]}: {archive_path.name}")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        if fmt == "zip":
            count, total = _extract_zip(archive_path, out_dir, options.overwrite, cb)
        elif fmt in ("tar", "tar.gz", "tar.bz2", "tar.xz", "tar.zst"):
            count, total = _extract_tar(archive_path, out_dir, fmt, options.overwrite, cb)
        elif fmt in ("gz", "bz2", "xz", "zst"):
            count, total = _extract_single(archive_path, out_dir, fmt, options.overwrite, cb)
        elif fmt == "7z":
            try:
                import py7zr  # noqa: F401
                count, total = _extract_7z_py7zr(archive_path, out_dir, options.overwrite, cb)
            except ImportError:
                count, total = _extract_bsdtar(archive_path, out_dir, fmt, options.overwrite, cb)
        elif fmt in _BSDTAR_FORMATS:
            count, total = _extract_bsdtar(archive_path, out_dir, fmt, options.overwrite, cb)
        else:  # pragma: no cover — detect_format and dispatch must stay in sync
            raise UnsupportedFormatError(f"Unsupported format: {fmt}")
    except (zipfile.BadZipFile, tarfile.TarError, lzma.LZMAError,
            zstandard.ZstdError, EOFError) as exc:
        raise UfzError(f"Archive is corrupted or cannot be extracted: {exc}") from exc

    cb.report(100)
    elapsed = time.monotonic() - started
    cb.log("success", f"Extracted ({FORMAT_LABELS[fmt]}): {count:,} files -> {out_dir}")
    return UnpackResult(file_count=count, block_count=0, total_size=total, elapsed=elapsed)
