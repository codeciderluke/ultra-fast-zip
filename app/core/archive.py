"""Low-level UFZ file format handling.

Layout::

    Header
        MAGIC            8 bytes  (b"UFZ1\\x00\\x00\\x00\\x01"; legacy b"FPK1..." readable)
        VERSION          uint16   (little-endian)
        METADATA_LENGTH  uint64
    Metadata JSON (UTF-8)
    Block Header #N
        RAW_SIZE         uint64
        COMPRESSED_SIZE  uint64
        XXH64            uint64   (v1/v2: CRC32 uint32, over the compressed data)
    Compressed Block #N
    ...

Version history:

- v1: zlib blocks, CRC32 checksums
- v2: Zstandard blocks, CRC32 checksums; ``codec`` metadata field added
- v3: checksums switched to xxHash64
"""
from __future__ import annotations

import json
import struct
import zlib
from typing import Any, BinaryIO, Iterator

import xxhash
import zstandard

MAGIC = b"UFZ1\x00\x00\x00\x01"
LEGACY_MAGIC = b"FPK1\x00\x00\x00\x01"  # archives created before the UFZ rename
FORMAT_VERSION = 3
SUPPORTED_VERSIONS = frozenset({1, 2, 3})
FORMAT_NAMES = frozenset({"UFZ", "FPK"})

CODEC_ZSTD = "zstd"
CODEC_ZLIB = "zlib"
DEFAULT_CODEC = CODEC_ZSTD
MAX_LEVEL = zstandard.MAX_COMPRESSION_LEVEL  # 22

HEADER = struct.Struct("<8sHQ")           # magic, version, metadata_length
BLOCK_HEADER = struct.Struct("<QQI")      # v1/v2: raw_size, compressed_size, crc32
BLOCK_HEADER_V3 = struct.Struct("<QQQ")   # v3:    raw_size, compressed_size, xxh64


def block_header_struct(version: int) -> struct.Struct:
    return BLOCK_HEADER_V3 if version >= 3 else BLOCK_HEADER


def digest(data, version: int = FORMAT_VERSION) -> int:
    """Version-appropriate checksum (v3+: xxHash64, older: CRC32)."""
    if version >= 3:
        return xxhash.xxh64_intdigest(data)
    return zlib.crc32(data) & 0xFFFFFFFF


def new_hasher(version: int = FORMAT_VERSION):
    """Streaming checksum: call ``update(chunk)`` then ``intdigest()``."""
    if version >= 3:
        return xxhash.xxh64()

    class _Crc32:
        def __init__(self) -> None:
            self._crc = 0

        def update(self, chunk) -> None:
            self._crc = zlib.crc32(chunk, self._crc)

        def intdigest(self) -> int:
            return self._crc & 0xFFFFFFFF

    return _Crc32()


class UfzError(Exception):
    """Base class for all UFZ processing errors."""


class InvalidArchiveError(UfzError):
    """Not a UFZ file, or the header is corrupt."""


class VersionMismatchError(UfzError):
    """Unsupported format version."""


class CorruptArchiveError(UfzError):
    """Data corruption such as a checksum mismatch."""


class OperationCancelled(UfzError):
    """The user cancelled the operation."""


def write_header(fp: BinaryIO, metadata: dict[str, Any]) -> bytes:
    """Write the header and metadata JSON; return the serialized metadata."""
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    fp.write(HEADER.pack(MAGIC, FORMAT_VERSION, len(payload)))
    fp.write(payload)
    return payload


def read_header(fp: BinaryIO) -> tuple[int, int]:
    """Read the header and return (version, metadata_length)."""
    raw = fp.read(HEADER.size)
    if len(raw) != HEADER.size:
        raise InvalidArchiveError("File too small to contain a UFZ header.")
    magic, version, metadata_length = HEADER.unpack(raw)
    if magic not in (MAGIC, LEGACY_MAGIC):
        raise InvalidArchiveError("Not a UFZ archive.")
    if version not in SUPPORTED_VERSIONS:
        raise VersionMismatchError(
            f"Unsupported format version: {version} "
            f"(supported: {', '.join(map(str, sorted(SUPPORTED_VERSIONS)))})"
        )
    return version, metadata_length


def read_metadata(fp: BinaryIO) -> dict[str, Any]:
    """Validate the header and return the parsed metadata JSON.

    Leaves the file pointer at the first block.
    """
    _, metadata_length = read_header(fp)
    raw = fp.read(metadata_length)
    if len(raw) != metadata_length:
        raise CorruptArchiveError("Metadata is truncated.")
    try:
        metadata = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorruptArchiveError(f"Cannot parse metadata: {exc}") from exc
    if not isinstance(metadata, dict) or metadata.get("format") not in FORMAT_NAMES:
        raise CorruptArchiveError("Invalid metadata structure.")
    return metadata


def make_compressor(level: int) -> zstandard.ZstdCompressor:
    """Create a Zstandard compressor meant to be reused across blocks."""
    level = max(1, min(int(level), MAX_LEVEL))
    return zstandard.ZstdCompressor(level=level)


def write_block(
    fp: BinaryIO,
    raw_data: bytes,
    level: int,
    compressor: zstandard.ZstdCompressor | None = None,
) -> int:
    """Compress a block with Zstandard, write it, return the compressed size."""
    if compressor is None:
        compressor = make_compressor(level)
    compressed = compressor.compress(raw_data)
    fp.write(BLOCK_HEADER_V3.pack(len(raw_data), len(compressed), digest(compressed)))
    fp.write(compressed)
    return len(compressed)


def read_block_header(fp: BinaryIO, version: int = FORMAT_VERSION) -> tuple[int, int, int]:
    """Read a block header and return (raw_size, compressed_size, digest)."""
    header = block_header_struct(version)
    raw = fp.read(header.size)
    if len(raw) != header.size:
        raise CorruptArchiveError("Block header is truncated.")
    return header.unpack(raw)


def read_block(fp: BinaryIO, codec: str = DEFAULT_CODEC, version: int = FORMAT_VERSION) -> bytes:
    """Read the block at the current position, verify, and decompress it."""
    raw_size, compressed_size, block_digest = read_block_header(fp, version)
    compressed = fp.read(compressed_size)
    if len(compressed) != compressed_size:
        raise CorruptArchiveError("Block data is truncated.")
    return decompress_block(compressed, raw_size, block_digest, codec, version)


def decompress_block(
    compressed,
    raw_size: int,
    block_digest: int,
    codec: str = DEFAULT_CODEC,
    version: int = FORMAT_VERSION,
    decompressor: zstandard.ZstdDecompressor | None = None,
) -> bytes:
    """Verify a compressed block's checksum and return the raw data.

    ``compressed`` may be bytes or a memoryview (mmap slice).
    Pass ``decompressor`` to reuse one per worker thread.
    """
    if digest(compressed, version) != block_digest:
        raise CorruptArchiveError("Block checksum mismatch; the file may be corrupted.")
    try:
        if codec == CODEC_ZSTD:
            if decompressor is None:
                decompressor = zstandard.ZstdDecompressor()
            raw = decompressor.decompress(compressed, max_output_size=raw_size)
        elif codec == CODEC_ZLIB:
            raw = zlib.decompress(compressed)
        else:
            raise CorruptArchiveError(f"Unknown compression codec: {codec}")
    except (zlib.error, zstandard.ZstdError) as exc:
        raise CorruptArchiveError(f"Block decompression failed: {exc}") from exc
    if len(raw) != raw_size:
        raise CorruptArchiveError("Block raw size mismatch.")
    return raw


def iter_block_locations(
    fp: BinaryIO, block_count: int, version: int = FORMAT_VERSION
) -> Iterator[tuple[int, int, int, int]]:
    """Scan block headers sequentially, yielding
    (data offset, raw_size, compressed_size, digest).

    The file pointer must be at the first block header when called.
    """
    for _ in range(block_count):
        raw_size, compressed_size, block_digest = read_block_header(fp, version)
        offset = fp.tell()
        yield offset, raw_size, compressed_size, block_digest
        fp.seek(compressed_size, 1)
