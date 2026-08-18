from __future__ import annotations

import re
from typing import List

from .models import LyricLine

_KRC_TAG = re.compile(r"\[\s*(\d+)\s*,\s*(\d+)\s*\]")
_LRC_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD_TAG = re.compile(r"<[^>]*>|\{[^}]*\}")


def _clean(text: str) -> str:
    return _WORD_TAG.sub("", text).replace("\ufeff", "").strip()


def parse_lyrics(text: str) -> List[LyricLine]:
    """Parse KRC or LRC lyric text into timestamped lines."""
    lines: List[LyricLine] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue

        krc_matches = list(_KRC_TAG.finditer(line))
        if krc_matches:
            for index, match in enumerate(krc_matches):
                end = (
                    krc_matches[index + 1].start()
                    if index + 1 < len(krc_matches)
                    else len(line)
                )
                body = _clean(line[match.end() : end])
                if body:
                    lines.append(LyricLine(int(match.group(1)), body))
            continue

        lrc_matches = list(_LRC_TAG.finditer(line))
        if lrc_matches:
            for index, match in enumerate(lrc_matches):
                end = (
                    lrc_matches[index + 1].start()
                    if index + 1 < len(lrc_matches)
                    else len(line)
                )
                body = _clean(line[match.end() : end])
                if body:
                    minutes = int(match.group(1))
                    seconds = int(match.group(2))
                    fraction = int((match.group(3) or "0").ljust(3, "0")[:3])
                    lines.append(
                        LyricLine(
                            minutes * 60000 + seconds * 1000 + fraction,
                            body,
                        )
                    )
            continue

    lines.sort(key=lambda item: (item.start_ms, item.text))
    unique: List[LyricLine] = []
    seen: set[tuple[int, str]] = set()
    for item in lines:
        key = (item.start_ms, item.text)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
