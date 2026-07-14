"""UFZ archive metadata models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileEntry:
    """Metadata for a single file inside the archive."""

    path: str
    size: int
    mtime: int
    mode: int
    block: int
    offset: int
    length: int
    checksum: int  # v3+: xxHash64, v1/v2: CRC32

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "mode": self.mode,
            "block": self.block,
            "offset": self.offset,
            "length": self.length,
            "hash": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileEntry":
        return cls(
            path=data["path"],
            size=int(data["size"]),
            mtime=int(data["mtime"]),
            mode=int(data["mode"]),
            block=int(data["block"]),
            offset=int(data["offset"]),
            length=int(data["length"]),
            checksum=int(data.get("hash", data.get("crc32", 0))),
        )


@dataclass
class ArchiveInfo:
    """Archive summary used by the Inspect tab."""

    version: int
    codec: str
    created: int
    block_size: int
    file_count: int
    block_count: int
    total_size: int
    compressed_size: int
    dirs: list[str] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return self.compressed_size / self.total_size * 100.0
