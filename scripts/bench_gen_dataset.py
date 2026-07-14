"""Generate a reproducible mixed benchmark dataset (fixed seed).

Composition (UFZ's target use case — many small files — plus a realistic mix):
- 4,000 small text files (1-40KB)  : source-code/config-like
- 400 medium JSON files (~300KB)   : semi-structured data
- 6 large logs (25MB)              : highly compressible
- 4 large binaries (20MB)          : moderately compressible
- 2 large random files (15MB)      : incompressible (pre-compressed media-like)
"""
import os
import random
import sys

OUT = sys.argv[1]
rng = random.Random(42)

WORDS = ("def return import class self value data result config option "
         "server client request response error status buffer stream block "
         "index count total size path name file folder archive compress").split()

def text_chunk(n):
    parts = []
    size = 0
    while size < n:
        line = " ".join(rng.choices(WORDS, k=rng.randint(4, 12))) + "\n"
        parts.append(line)
        size += len(line)
    return "".join(parts).encode()

def make(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)

total = 0
# Small text files spread across 40 subfolders
for i in range(4000):
    d = text_chunk(rng.randint(1024, 40 * 1024))
    make(os.path.join(OUT, "src", f"mod{i % 40:02d}", f"file_{i:04d}.py"), d)
    total += len(d)

for i in range(400):
    rows = []
    for j in range(rng.randint(800, 1200)):
        rows.append('{"id":%d,"name":"%s","value":%.6f,"tags":["%s","%s"]}'
                    % (j, rng.choice(WORDS), rng.random(),
                       rng.choice(WORDS), rng.choice(WORDS)))
    d = ("[\n" + ",\n".join(rows) + "\n]\n").encode()
    make(os.path.join(OUT, "data", f"records_{i:03d}.json"), d)
    total += len(d)

# Large logs (highly repetitive)
for i in range(6):
    lines = []
    for j in range(300000):
        lines.append("2026-07-14 12:%02d:%02d INFO  worker-%d processed block %d ok\n"
                     % (j // 3600 % 60, j % 60, j % 8, j))
    d = ("".join(lines))[:25 * 1024 * 1024].encode()
    make(os.path.join(OUT, "logs", f"app_{i}.log"), d)
    total += len(d)

# Large binaries (repeating pattern + noise = medium compressibility)
for i in range(4):
    pattern = bytes(rng.randrange(256) for _ in range(4096))
    noise = rng.randbytes(4096)
    blocks = []
    for j in range(20 * 1024 * 1024 // 8192):
        blocks.append(pattern)
        blocks.append(noise[: rng.randint(1024, 4096)].ljust(4096, b"\0"))
    d = b"".join(blocks)[:20 * 1024 * 1024]
    make(os.path.join(OUT, "bin", f"asset_{i}.bin"), d)
    total += len(d)

# Large random files (incompressible)
for i in range(2):
    d = rng.randbytes(15 * 1024 * 1024)
    make(os.path.join(OUT, "media", f"video_{i}.mp4"), d)
    total += len(d)

print(f"dataset ready: {total / 1048576:.1f} MB")
