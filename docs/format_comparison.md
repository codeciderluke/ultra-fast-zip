# UFZ vs Existing Archive Formats

Measured: 2026-07-14 · Environment: i9-12900K (16C/24T), Windows 11, NVMe SSD

## 1. Contenders

| Format | Algorithm | Implementation | Compression unit |
|--------|-----------|----------------|------------------|
| **UFZ v3** | Zstandard L6 + xxHash64 | this project (Python + C libs) | 8MB solid blocks |
| ZIP | Deflate L6 + CRC32 | Python `zipfile` | per file |
| tar.gz | gzip (Deflate) L6 | bsdtar 3.8.4 (native C) | whole-stream solid |
| tar.zst | Zstandard L6 | bsdtar 3.8.4 (native C) | whole-stream solid |
| tar.xz | LZMA L6 | bsdtar 3.8.4 (native C) | whole-stream solid |

- tar.xz stands in for the 7-Zip/LZMA family of high-ratio compressors.
- tar.zst uses the **same codec and level as UFZ**, isolating the effect of
  **format design** rather than codec choice.

## 2. Method

- Dataset: 4,412 files / 321.8 MB mixed — 4,000 small text files (1-40KB),
  400 medium JSON (~300KB), 6 highly compressible logs (25MB), 4 medium-
  compressibility binaries (20MB), 2 incompressible random files (15MB).
  Reflects UFZ's target workload (many small files) with large/incompressible
  files mixed in to reduce bias.
- Each job run twice, minimum taken (mitigates OS cache/noise).
- Restored trees verified against the source by full CRC32 — **all formats PASS**.
- Reproduce: `python scripts/bench_gen_dataset.py <dataset>` then
  `python scripts/bench_multi.py <dataset> <workdir>`
  (root-level `benchmark.py` is the two-way UFZ vs ZIP tool).

## 3. Results

| Format | Pack | Unpack | Size | Ratio | Integrity |
|--------|-----:|-------:|-----:|------:|:---------:|
| **UFZ (zstd)** | **2.0s** | **0.8s** | 54.6 MB | 17.0% | PASS |
| ZIP (deflate) | 5.5s | 1.8s | 61.5 MB | 19.1% | PASS |
| tar.gz (gzip) | 5.2s | 1.2s | 58.7 MB | 18.3% | PASS |
| tar.zst (zstd) | 1.6s | 1.2s | 54.2 MB | 16.8% | PASS |
| tar.xz (LZMA) | 93.3s | 1.8s | **46.0 MB** | **14.3%** | PASS |

Relative to UFZ:

| vs | Pack speed | Unpack speed | Size |
|----|-----------:|-------------:|-----:|
| ZIP | **2.7x faster** | **2.2x faster** | 11.3% smaller |
| tar.gz | 2.6x faster | 1.5x faster | 7.0% smaller |
| tar.zst | 0.77x (23% slower) | 1.5x faster | 0.8% larger (par) |
| tar.xz | 46x faster | 2.2x faster | 18.7% larger |

## 4. Interpretation

### 4.1 vs ZIP — the main rival; UFZ wins across the board

- **Ratio**: ZIP compresses **each file independently**, so with thousands of
  small files it never exploits cross-file redundancy and pays per-file Deflate
  header/warm-up costs. UFZ's 8MB solid blocks capture cross-file redundancy.
- **Speed**: the generational gap between Deflate (1995) and Zstandard (2016),
  multiplied by UFZ's parallel extraction pipeline (mmap zero-copy → N decompress
  workers → N write workers).
- ZIP's remaining advantages are ubiquity (OS-native support) and per-file random
  access; UFZ offers block-level random access (instant inspect, partial-extract-
  capable structure).

### 4.2 vs tar.zst — same codec, isolating format design

- **Size within 0.8% (par)**: expected with identical codec/level. UFZ is
  marginally larger due to compression-context breaks at block boundaries plus
  block headers/JSON metadata.
- **Pack 23% slower**: UFZ's pack path is currently **single-threaded** with
  Python-level scan/buffer overhead; bsdtar is pure C. → top improvement
  candidate (§6).
- **Unpack 1.5x faster**: a single-stream tar.zst cannot be extracted in
  parallel, structurally. UFZ blocks are independent, so extraction spreads
  across all cores. **This is the core value of the format design**, and the gap
  widens with more cores and bigger data.
- tar.zst also scatters metadata through the stream, so even listing files
  requires decompressing everything; UFZ reads its up-front JSON metadata
  instantly.

### 4.3 vs tar.xz (LZMA) — the ratio/speed trade-off

- LZMA wins on ratio (14.3% vs 17.0%) but packs **46x slower** (93.3s vs 2.0s).
- Practical only for "compress once, download many" distribution scenarios; not
  for UFZ's target workflow of repeated folder backup/transfer.
- Note: UFZ at zstd level 19-22 approaches LZMA ratios at typically 2-5x LZMA's
  speed.

### 4.4 vs tar.gz — legacy stream compression

- No axis where it beats UFZ. Solid-stream gzip out-compresses ZIP but shares
  Deflate's speed ceiling and cannot extract in parallel. Its only remaining
  reason to exist is legacy compatibility.

## 5. Design comparison

| Property | UFZ v3 | ZIP | tar.gz/xz | tar.zst | 7z |
|----------|--------|-----|-----------|---------|-----|
| Compression unit | solid blocks (8MB) | per file | whole solid | whole solid | selectable |
| Many-small-files ratio | good | poor | good | good | good |
| Parallel extraction | **per block** | per file¹ | no | no | limited |
| Partial/random access | per block | per file | no (full scan) | no | not when solid |
| List cost | header only (instant) | central directory (instant) | full scan | full scan | header (instant) |
| Integrity | block+file dual (xxh64) | file CRC32 | stream CRC/none | frame xxh64 | file CRC32 |
| Streaming creation | yes (via temp file) | yes | yes | yes | yes |
| Encryption | no | yes (weak/AES) | no | no | yes (AES-256) |
| Ecosystem | own tools only | de-facto standard | Unix standard | growing | widespread |

¹ The ZIP format permits per-file parallel extraction, but most implementations
(including Python `zipfile`) extract sequentially.

**UFZ's position**: a block-level compromise between whole-solid compression
ratios and per-file parallelism/random access. Prior art includes ZPAQ blocks,
SquashFS, and zstd's seekable format; UFZ adds up-front metadata (instant
inspect) and dual checksums in a practical implementation.

## 6. Limitations and improvement candidates

1. **Parallel packing (big win)** — packing is single-threaded and loses 23% to
   (also single-threaded) C tar.zst. Blocks are independent, so a
   read → N compress workers → write pipeline mirrors extraction;
   `ZstdCompressor(threads=N)` alone would already help.
2. **JSON metadata** — parsing/memory may bottleneck at hundreds of thousands of
   files; a fixed-width binary index is a candidate.
3. **Temp-file assembly** — blocks are written to `.blocks.tmp` then copied,
   doubling disk writes; reserving header space would enable single-pass output.
4. **No encryption** — a gap versus 7z/ZIP (AES) for sensitive data.
5. **Ubiquity** — the fate of any custom format: recipients need the ufz CLI/GUI
   (mitigated by the multi-format extraction support).

## 7. Conclusions

- **UFZ replaces ZIP outright for its target workload** (repeatedly packing and
  unpacking trees of many small files): 2.7x faster pack, 2.2x faster unpack,
  11% smaller.
- Against same-codec tar.zst, ratio is par while extraction is 1.5x faster with
  instant listing — the measured value of block-solid design. The remaining 23%
  pack-speed gap is addressable via pack parallelization.
- When maximum ratio matters, LZMA still wins (18.7% smaller) at a 46x time
  cost; for iterative workflows, UFZ/zstd is the rational choice.
