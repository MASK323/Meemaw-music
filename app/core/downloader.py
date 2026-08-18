from __future__ import annotations

import re
import shutil
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .models import Song

_INVALID = re.compile(r'[\\/:*?"<>|\r\n]+')


def _safe_name(text: str) -> str:
    name = _INVALID.sub(" ", text or "").strip()
    return name[:80] or "未命名"


def download_rank_songs(
    songs: List[Song],
    resolve_url: Callable[[str], dict],
    progress: Optional[Callable[[str], None]] = None,
    dest_dir: Optional[Path] = None,
) -> Tuple[int, List[str]]:
    dest = Path(dest_dir or Path.home() / "Downloads" / "Meemaw music")
    dest.mkdir(parents=True, exist_ok=True)
    ok = 0
    failures: List[str] = []
    total = len(songs)
    for index, song in enumerate(songs):
        if progress is not None:
            progress(f"正在下载 {index + 1}/{total}：{song.title}")
        try:
            if not song.kugou_hash:
                raise RuntimeError("没有可用的网络音源")
            info = resolve_url(song.kugou_hash)
            url = (info or {}).get("url") or ""
            if not url:
                raise RuntimeError("没有解析到音频地址")
            filename = dest / f"{_safe_name(song.artist)} - {_safe_name(song.title)}.mp3"
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Referer": "http://www.kugou.com/",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as source:
                with open(filename, "wb") as handle:
                    shutil.copyfileobj(source, handle)
            ok += 1
        except Exception as exc:
            failures.append(f"{song.title}：{exc}")
    return ok, failures
