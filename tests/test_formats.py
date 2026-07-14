"""Format auto-detection and multi-format extraction tests."""
from __future__ import annotations

import gzip
import io
import tarfile
import zipfile
from pathlib import Path

import pytest
import zstandard

from app.core.formats import UnsupportedFormatError, detect_format, extract_archive
from app.core.packer import PackOptions, pack
from app.utils.path_utils import UnsafeArchivePathError

FILES = {
    "a.txt": b"hello world" * 100,
    "docs/readme.md": "# readme\nnon-ascii: café résumé".encode("utf-8"),
    "docs/sub/deep.bin": bytes(range(256)) * 40,
}


@pytest.fixture
def src_tree(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    for rel, data in FILES.items():
        target = src / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return src


def _make_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, data in FILES.items():
            zf.writestr(rel, data)


def _make_tar(path: Path, mode: str) -> None:
    with tarfile.open(path, mode) as tf:
        for rel, data in FILES.items():
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def _assert_extracted(out: Path) -> None:
    for rel, data in FILES.items():
        assert (out / rel).read_bytes() == data, rel


def test_detect_ufz(src_tree: Path, tmp_path: Path):
    archive = tmp_path / "a.ufz"
    pack(src_tree, archive, PackOptions())
    assert detect_format(archive) == "ufz"


def test_detect_zip(tmp_path: Path):
    archive = tmp_path / "a.zip"
    _make_zip(archive)
    assert detect_format(archive) == "zip"


def test_detect_tar_variants(tmp_path: Path):
    plain = tmp_path / "a.tar"
    _make_tar(plain, "w")
    assert detect_format(plain) == "tar"

    gz = tmp_path / "a.tar.gz"
    _make_tar(gz, "w:gz")
    assert detect_format(gz) == "tar.gz"


def test_detect_single_gz(tmp_path: Path):
    archive = tmp_path / "note.txt.gz"
    with gzip.open(archive, "wb") as fp:
        fp.write(b"plain gz payload")
    assert detect_format(archive) == "gz"


def test_detect_unknown(tmp_path: Path):
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"\x00\x01\x02\x03 not an archive")
    assert detect_format(junk) is None
    with pytest.raises(UnsupportedFormatError):
        extract_archive(junk, tmp_path / "out")


def test_extract_zip(tmp_path: Path):
    archive = tmp_path / "a.zip"
    _make_zip(archive)
    out = tmp_path / "out"
    result = extract_archive(archive, out)
    assert result.file_count == len(FILES)
    _assert_extracted(out)


def test_extract_tar_gz(tmp_path: Path):
    archive = tmp_path / "a.tar.gz"
    _make_tar(archive, "w:gz")
    out = tmp_path / "out"
    result = extract_archive(archive, out)
    assert result.file_count == len(FILES)
    _assert_extracted(out)


def test_extract_tar_zst(tmp_path: Path):
    # Build a zstd-compressed tar (tarfile has no native zst support)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for rel, data in FILES.items():
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    archive = tmp_path / "a.tar.zst"
    archive.write_bytes(zstandard.ZstdCompressor().compress(buf.getvalue()))
    assert detect_format(archive) == "tar.zst"
    out = tmp_path / "out"
    extract_archive(archive, out)
    _assert_extracted(out)


def test_extract_single_gz(tmp_path: Path):
    archive = tmp_path / "note.txt.gz"
    payload = b"single-file gzip payload" * 10
    with gzip.open(archive, "wb") as fp:
        fp.write(payload)
    out = tmp_path / "out"
    result = extract_archive(archive, out)
    assert result.file_count == 1
    assert (out / "note.txt").read_bytes() == payload


def test_extract_ufz_via_dispatcher(src_tree: Path, tmp_path: Path):
    archive = tmp_path / "a.ufz"
    pack(src_tree, archive, PackOptions())
    out = tmp_path / "out"
    result = extract_archive(archive, out)
    assert result.file_count == len(FILES)
    _assert_extracted(out)


def test_zip_slip_rejected(tmp_path: Path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escape.txt", b"boom")
    with pytest.raises(UnsafeArchivePathError):
        extract_archive(evil, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_zip_overwrite_refused(tmp_path: Path):
    archive = tmp_path / "a.zip"
    _make_zip(archive)
    out = tmp_path / "out"
    extract_archive(archive, out)
    with pytest.raises(FileExistsError):
        extract_archive(archive, out)
    from app.core.unpacker import UnpackOptions

    extract_archive(archive, out, UnpackOptions(overwrite=True))
    _assert_extracted(out)


def test_extract_7z(tmp_path: Path):
    py7zr = pytest.importorskip("py7zr")
    archive = tmp_path / "a.7z"
    with py7zr.SevenZipFile(archive, "w") as zf:
        for rel, data in FILES.items():
            zf.writestr(data, rel)
    assert detect_format(archive) == "7z"
    out = tmp_path / "out"
    extract_archive(archive, out)
    _assert_extracted(out)
