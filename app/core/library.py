from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List, Optional

from mutagen import File as MutagenFile
from PySide6.QtCore import QObject, Signal

from .models import Song

AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".wma", ".opus"}


def _extract_cover(audio) -> Optional[bytes]:
    try:
        tags = getattr(audio, "tags", None)
        if tags is None:
            return None
        pictures = getattr(tags, "pictures", None)
        if pictures:
            return bytes(pictures[0].data)
        getall = getattr(tags, "getall", None)
        if getall is not None:
            for frame in getall("APIC"):
                return bytes(frame.data)
        if "covr" in tags:
            for cover in tags["covr"]:
                return bytes(cover)
    except Exception:
        return None
    return None


def read_song(path: str) -> Optional[Song]:
    try:
        audio = MutagenFile(path, easy=False)
        if audio is None or audio.info is None:
            return None
        tags = audio.tags
        title = ""
        artist = ""
        album = ""
        if tags is not None:
            title = str(tags.get("title", [""])[0] if "title" in tags else "")
            artist = str(tags.get("artist", [""])[0] if "artist" in tags else "")
            album = str(tags.get("album", [""])[0] if "album" in tags else "")
        name = Path(path).stem
        return Song(
            title=title or name,
            artist=artist or "未知歌手",
            album=album,
            duration=float(getattr(audio.info, "length", 0.0) or 0.0),
            local_path=os.path.abspath(path),
            cover_data=_extract_cover(audio),
            source="本地",
        )
    except Exception:
        return None


def scan_folder(root: str) -> List[Song]:
    songs = []
    for dirpath, _, filenames in os.walk(root):
        for filename in sorted(filenames):
            ext = Path(filename).suffix.lower()
            if ext not in AUDIO_EXTENSIONS:
                continue
            song = read_song(os.path.join(dirpath, filename))
            if song is not None:
                songs.append(song)
    return songs


class LibraryScanner(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def scan_in_thread(self, root: str) -> None:
        thread = threading.Thread(target=self._run, args=(root,), daemon=True)
        thread.start()

    def _run(self, root: str) -> None:
        try:
            self.progress.emit("正在扫描音乐文件夹…")
            songs = scan_folder(root)
            self.finished.emit(songs)
        except Exception as exc:
            self.failed.emit(str(exc))
