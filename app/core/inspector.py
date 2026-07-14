"""Archive summary inspection for ``.ufz`` files."""
from __future__ import annotations

from pathlib import Path

from app.core.archive import CODEC_ZLIB, read_metadata
from app.core.models import ArchiveInfo, FileEntry


def inspect(archive_path: Path) -> ArchiveInfo:
    """Return archive summary information and the file list."""
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive does not exist: {archive_path}")

    with open(archive_path, "rb") as fp:
        metadata = read_metadata(fp)

    files = [FileEntry.from_dict(item) for item in metadata.get("files", [])]
    total_size = sum(entry.size for entry in files)

    return ArchiveInfo(
        version=int(metadata.get("version", 0)),
        codec=str(metadata.get("codec", CODEC_ZLIB)),
        created=int(metadata.get("created", 0)),
        block_size=int(metadata.get("block_size", 0)),
        file_count=int(metadata.get("file_count", len(files))),
        block_count=int(metadata.get("block_count", 0)),
        total_size=total_size,
        compressed_size=archive_path.stat().st_size,
        dirs=list(metadata.get("dirs", [])),
        files=files,
    )
