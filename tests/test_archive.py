"""Low-level UFZ format tests."""
from __future__ import annotations

import io

import pytest

from app.core import archive


def test_header_roundtrip():
    buf = io.BytesIO()
    metadata = {"format": "UFZ", "version": 1, "files": []}
    archive.write_header(buf, metadata)
    buf.seek(0)
    parsed = archive.read_metadata(buf)
    assert parsed == metadata


def test_legacy_fpk_magic_accepted():
    # Archives created before the UFZ rename must stay readable
    buf = io.BytesIO(archive.HEADER.pack(archive.LEGACY_MAGIC, 3, 0))
    version, meta_len = archive.read_header(buf)
    assert version == 3
    assert meta_len == 0


def test_invalid_magic_rejected():
    buf = io.BytesIO(b"NOTUFZ00" + b"\x00" * 10)
    with pytest.raises(archive.InvalidArchiveError):
        archive.read_header(buf)


def test_truncated_header_rejected():
    buf = io.BytesIO(b"UFZ1")
    with pytest.raises(archive.InvalidArchiveError):
        archive.read_header(buf)


def test_version_mismatch_rejected():
    buf = io.BytesIO(archive.HEADER.pack(archive.MAGIC, 99, 0))
    with pytest.raises(archive.VersionMismatchError):
        archive.read_header(buf)


def test_block_roundtrip():
    buf = io.BytesIO()
    data = b"hello ufz block" * 1000
    archive.write_block(buf, data, level=6)
    buf.seek(0)
    assert archive.read_block(buf) == data


def test_block_crc_mismatch_rejected():
    buf = io.BytesIO()
    data = b"payload" * 100
    archive.write_block(buf, data, level=6)
    raw = bytearray(buf.getvalue())
    raw[-1] ^= 0xFF  # corrupt the last byte of compressed data
    corrupted = io.BytesIO(bytes(raw))
    with pytest.raises(archive.CorruptArchiveError):
        archive.read_block(corrupted)


def test_iter_block_locations():
    buf = io.BytesIO()
    blocks = [b"a" * 100, b"b" * 200, b"c" * 300]
    for block in blocks:
        archive.write_block(buf, block, level=1)
    buf.seek(0)
    locations = list(archive.iter_block_locations(buf, len(blocks)))
    assert len(locations) == 3
    for (offset, raw_size, comp_size, crc), original in zip(locations, blocks):
        buf.seek(offset)
        compressed = buf.read(comp_size)
        assert archive.decompress_block(compressed, raw_size, crc) == original
