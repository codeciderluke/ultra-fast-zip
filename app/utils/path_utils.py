"""Path utilities, including Zip Slip (path traversal) protection."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


class UnsafeArchivePathError(ValueError):
    """An archive-internal path escapes the output directory."""


def normalize_archive_path(path: Path, base: Path) -> str:
    """Convert a real file path to a relative POSIX path for the archive."""
    return path.relative_to(base).as_posix()


def safe_join(output_dir: Path | str, relative_path: str) -> Path:
    """Return a target path confined to the output directory.

    Rejects absolute paths, drive letters, and ``..`` components with
    :class:`UnsafeArchivePathError`. String-only validation — no syscalls —
    so it stays fast for tens of thousands of paths.
    """
    if not relative_path or relative_path.startswith(("/", "\\")):
        raise UnsafeArchivePathError(f"Unsafe archive path: {relative_path}")
    for part in relative_path.split("/"):
        if part in ("", ".", "..") or ":" in part or "\\" in part:
            raise UnsafeArchivePathError(f"Unsafe archive path: {relative_path}")

    base = os.path.abspath(str(output_dir))
    target = os.path.normpath(os.path.join(base, relative_path))
    if target != base and not target.startswith(base + os.sep):
        raise UnsafeArchivePathError(f"Unsafe archive path: {relative_path}")
    return Path(target)


def is_hidden(path: Path | str) -> bool:
    """True for dotfiles; on Windows also checks the hidden attribute."""
    name = os.path.basename(str(path))
    if name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            attrs = os.stat(path, follow_symlinks=False).st_file_attributes
            return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)
        except OSError:
            return False
    return False


def default_output_archive(folder: Path) -> Path:
    """Default archive path suggested when compressing (e.g. my_folder.ufz)."""
    return folder.parent / f"{folder.name}.ufz"


def default_output_folder(archive: Path) -> Path:
    """Default output folder suggested when extracting (e.g. archive_extracted)."""
    stem = archive.stem
    if stem.lower().endswith(".tar"):  # x.tar.gz -> x, not x.tar
        stem = stem[:-4]
    return archive.parent / f"{stem}_extracted"
