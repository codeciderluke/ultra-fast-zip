"""Display formatting utilities."""
from __future__ import annotations

import time

_UNITS = ["B", "KB", "MB", "GB", "TB"]


def human_size(size: float) -> str:
    for unit in _UNITS:
        if size < 1024 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_ratio(total_size: int, compressed_size: int) -> str:
    if total_size <= 0:
        return "-"
    return f"{compressed_size / total_size * 100:.1f}%"


def format_timestamp(epoch: int) -> str:
    if not epoch:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))
