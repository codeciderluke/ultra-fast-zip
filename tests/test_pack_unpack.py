"""Pack/unpack roundtrip, security, and error-handling tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core import archive
from app.core.inspector import inspect
from app.core.packer import PackOptions, pack
from app.core.unpacker import UnpackOptions, unpack
from app.utils.path_utils import UnsafeArchivePathError, safe_join


@pytest.fixture
def sample_tree(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    (src / "docs" / "sub").mkdir(parents=True)
    (src / "empty_dir").mkdir()
    (src / "a.txt").write_bytes(b"hello world" * 100)
    (src / "b.bin").write_bytes(os.urandom(50_000))
    (src / "docs" / "readme.md").write_text("# readme\nnon-ascii: café résumé", encoding="utf-8")
    (src / "docs" / "sub" / "deep.txt").write_bytes(b"deep" * 10)
    (src / "zero.dat").write_bytes(b"")
    return src


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def test_pack_unpack_roundtrip(sample_tree: Path, tmp_path: Path):
    out_ufz = tmp_path / "out.ufz"
    result = pack(sample_tree, out_ufz, PackOptions(block_size=16 * 1024, level=6))
    assert out_ufz.exists()
    assert result.file_count == 5

    dest = tmp_path / "extracted"
    unpack(out_ufz, dest, UnpackOptions(threads=2))

    assert _tree_snapshot(dest) == _tree_snapshot(sample_tree)
    assert (dest / "empty_dir").is_dir()
    assert (dest / "zero.dat").read_bytes() == b""


def test_small_block_size_creates_multiple_blocks(sample_tree: Path, tmp_path: Path):
    out_ufz = tmp_path / "out.ufz"
    result = pack(sample_tree, out_ufz, PackOptions(block_size=1024, level=1))
    assert result.block_count > 1

    info = inspect(out_ufz)
    assert info.block_count == result.block_count
    assert info.file_count == result.file_count


def test_inspect_reports_metadata(sample_tree: Path, tmp_path: Path):
    out_ufz = tmp_path / "out.ufz"
    pack(sample_tree, out_ufz, PackOptions())
    info = inspect(out_ufz)
    assert info.version == archive.FORMAT_VERSION
    assert info.file_count == 5
    assert info.total_size == sum(
        p.stat().st_size for p in sample_tree.rglob("*") if p.is_file()
    )
    assert {entry.path for entry in info.files} == {
        "a.txt",
        "b.bin",
        "docs/readme.md",
        "docs/sub/deep.txt",
        "zero.dat",
    }
    assert "empty_dir" in info.dirs


def test_missing_input_folder_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        pack(tmp_path / "nope", tmp_path / "out.ufz")


def test_non_ufz_file_rejected(tmp_path: Path):
    fake = tmp_path / "fake.ufz"
    fake.write_bytes(b"this is not a ufz file at all")
    with pytest.raises(archive.InvalidArchiveError):
        unpack(fake, tmp_path / "out")


def test_overwrite_refused_by_default(sample_tree: Path, tmp_path: Path):
    out_ufz = tmp_path / "out.ufz"
    pack(sample_tree, out_ufz, PackOptions())
    dest = tmp_path / "extracted"
    unpack(out_ufz, dest, UnpackOptions())
    with pytest.raises(FileExistsError):
        unpack(out_ufz, dest, UnpackOptions(overwrite=False))
    unpack(out_ufz, dest, UnpackOptions(overwrite=True))


def test_corrupted_block_detected(sample_tree: Path, tmp_path: Path):
    out_ufz = tmp_path / "out.ufz"
    pack(sample_tree, out_ufz, PackOptions())
    data = bytearray(out_ufz.read_bytes())
    data[-1] ^= 0xFF  # corrupt the last block's data
    out_ufz.write_bytes(bytes(data))
    with pytest.raises(archive.CorruptArchiveError):
        unpack(out_ufz, tmp_path / "extracted", UnpackOptions())


def test_safe_join_blocks_traversal(tmp_path: Path):
    for evil in ("../../evil.exe", "/home/user/.ssh/id_rsa", "C:\\Windows\\evil.dll", "a/../../b"):
        with pytest.raises(UnsafeArchivePathError):
            safe_join(tmp_path, evil)
    assert safe_join(tmp_path, "sub/file.txt") == (tmp_path / "sub" / "file.txt").resolve()


def test_malicious_archive_path_rejected(sample_tree: Path, tmp_path: Path):
    """An archive with a traversal path in its metadata is rejected before writing."""
    out_ufz = tmp_path / "out.ufz"
    pack(sample_tree, out_ufz, PackOptions())

    with open(out_ufz, "rb") as fp:
        _, meta_len = archive.read_header(fp)
        metadata = json.loads(fp.read(meta_len).decode("utf-8"))
        rest = fp.read()
    metadata["files"][0]["path"] = "../../evil.exe"

    hacked = tmp_path / "hacked.ufz"
    with open(hacked, "wb") as fp:
        archive.write_header(fp, metadata)
        fp.write(rest)

    with pytest.raises(UnsafeArchivePathError):
        unpack(hacked, tmp_path / "victim", UnpackOptions())
    assert not (tmp_path.parent / "evil.exe").exists()


def test_v1_zlib_archive_backward_compatible(tmp_path: Path):
    """Version 1 (zlib, FPK magic, no codec field) archives still extract."""
    import zlib as _zlib

    payload = b"legacy zlib content" * 50
    compressed = _zlib.compress(payload, 6)
    crc = _zlib.crc32(compressed) & 0xFFFFFFFF

    metadata = {
        "format": "FPK",
        "version": 1,
        "created": 1720000000,
        "block_size": 8388608,
        "file_count": 1,
        "block_count": 1,
        "dirs": [],
        "files": [{
            "path": "legacy.txt",
            "size": len(payload),
            "mtime": 1720000000,
            "mode": 0o644,
            "block": 0,
            "offset": 0,
            "length": len(payload),
            "crc32": _zlib.crc32(payload) & 0xFFFFFFFF,
        }],
    }

    legacy = tmp_path / "legacy.fpk"
    with open(legacy, "wb") as fp:
        body = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        fp.write(archive.HEADER.pack(archive.LEGACY_MAGIC, 1, len(body)))
        fp.write(body)
        fp.write(archive.BLOCK_HEADER.pack(len(payload), len(compressed), crc))
        fp.write(compressed)

    dest = tmp_path / "legacy_out"
    unpack(legacy, dest, UnpackOptions())
    assert (dest / "legacy.txt").read_bytes() == payload


def test_new_archive_uses_zstd_and_ufz_format(sample_tree: Path, tmp_path: Path):
    out_ufz = tmp_path / "out.ufz"
    pack(sample_tree, out_ufz, PackOptions())
    info = inspect(out_ufz)
    assert info.version == archive.FORMAT_VERSION
    assert info.codec == "zstd"
    with open(out_ufz, "rb") as fp:
        assert fp.read(8) == archive.MAGIC


def test_exclude_hidden_files(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "visible.txt").write_text("v")
    (src / ".hidden.txt").write_text("h")
    out_ufz = tmp_path / "out.ufz"
    pack(src, out_ufz, PackOptions(include_hidden=False))
    info = inspect(out_ufz)
    assert {entry.path for entry in info.files} == {"visible.txt"}
