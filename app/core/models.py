from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


@dataclass
class Song:
    title: str = "未知歌曲"
    artist: str = "未知歌手"
    album: str = ""
    duration: float = 0.0
    url: str = ""
    local_path: str = ""
    cover_url: str = ""
    cover_data: Optional[bytes] = None
    track_id: str = ""
    source: str = "本地"
    fallback_url: str = ""
    kugou_hash: str = ""

    @property
    def key(self) -> str:
        if self.local_path:
            return "local:" + self.local_path.replace("\\", "/")
        if self.kugou_hash:
            return "kugou:" + str(self.kugou_hash)
        if self.track_id:
            return "audius:" + str(self.track_id)
        return "url:" + (self.url or f"{self.title}|{self.artist}")

    @property
    def display(self) -> str:
        return f"{self.title} - {self.artist}"

    def time_text(self) -> str:
        return format_duration(self.duration)


@dataclass
class LyricLine:
    start_ms: int
    text: str


@dataclass
class AlbumCard:
    title: str
    artist: str
    cover_url: str = ""
    url: str = ""
    album_id: str = ""


@dataclass
class BannerItem:
    title: str
    subtitle: str
    cover_url: str = ""
    song: Optional[Song] = None
