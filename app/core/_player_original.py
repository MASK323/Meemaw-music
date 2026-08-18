from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from .audio_proxy import proxy_url, release_urls
from .models import Song

REPEAT_OFF = "off"
REPEAT_ONE = "one"
REPEAT_ALL = "all"

PLAY_MODE_ORDER = "order"
PLAY_MODE_LIST = "list"
PLAY_MODE_ONE = "one"
PLAY_MODE_SHUFFLE = "shuffle"
PLAY_MODE_CYCLE = [
    PLAY_MODE_ORDER,
    PLAY_MODE_LIST,
    PLAY_MODE_ONE,
    PLAY_MODE_SHUFFLE,
]


def _split_urls(value: str) -> List[str]:
    if not value:
        return []
    return [part for part in str(value).split("||") if part]


class PlayerManager(QObject):
    song_changed = Signal(object)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    state_changed = Signal(str)
    queue_changed = Signal(object)
    play_failed = Signal(str)
    url_ready = Signal(object, str, object)
    url_prefetched = Signal(object, str, object)
    loading_changed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.url_resolver: Optional[Callable[..., dict]] = None
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.5)

        self._queue: List[Song] = []
        self._index = -1
        self.shuffle = False
        self.repeat = REPEAT_OFF
        self.play_mode = PLAY_MODE_ORDER
        self._rng = random.Random()
        self._resolve_serial = 0
        self._resolve_pool = ThreadPoolExecutor(
            max_workers=10, thread_name_prefix="mm-url"
        )
        self._resolving_keys: set[str] = set()
        self._pending_key: Optional[str] = None
        self._fallback_failures = 0
        self._resolve_retries = 0
        self._failed_url_keys: set[str] = set()
        self._attempted_urls: List[str] = []
        self._last_position = 0

        self._position_emit = QTimer(self)
        self._position_emit.setInterval(200)
        self._position_emit.timeout.connect(self._emit_position)

        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(12000)
        self._loading_timer.setSingleShot(True)
        self._loading_timer.timeout.connect(self._on_loading_timeout)

        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self.duration_changed.emit)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)
        self.url_ready.connect(self._on_url_ready)
        self.url_prefetched.connect(self._on_url_prefetched)

    @property
    def queue(self) -> List[Song]:
        return list(self._queue)

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def current_song(self) -> Optional[Song]:
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return None

    @property
    def state(self) -> str:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            return "playing"
        if state == QMediaPlayer.PlaybackState.PausedState:
            return "paused"
        return "stopped"

    @property
    def position(self) -> int:
        return int(self._player.position())

    @property
    def duration(self) -> int:
        return int(self._player.duration())

    def play_song(self, song: Song) -> None:
        index = next((i for i, s in enumerate(self._queue) if s.key == song.key), -1)
        if index < 0:
            self._queue.append(song)
            index = len(self._queue) - 1
        self._index = index
        self.queue_changed.emit(self.queue)
        self._start_current()

    def play_queue(self, songs: List[Song], index: int = 0) -> None:
        if not songs:
            return
        self._queue = list(songs)
        self._index = max(0, min(index, len(songs) - 1))
        self.queue_changed.emit(self.queue)
        self._start_current()

    def reload_current(self) -> None:
        song = self.current_song
        if song is None:
            return
        self._failed_url_keys.clear()
        self._attempted_urls.clear()
        self._fallback_failures = 0
        self._resolve_retries = 0
        if song.kugou_hash:
            song.url = ""
            song.fallback_url = ""
            self._resolve_kugou_url(song)
        elif song.url:
            self._play_url(song.url)

    def _start_current(self) -> None:
        song = self.current_song
        if song is None:
            return
        self._failed_url_keys.clear()
        self._attempted_urls.clear()
        self._fallback_failures = 0
        self._resolve_retries = 0
        if song.local_path:
            self._loading_timer.stop()
            self._position_emit.stop()
            self._player.setSource(QUrl.fromLocalFile(song.local_path))
            self._player.play()
            self.song_changed.emit(song)
            self._prefetch_next()
            return
        if song.url:
            self._play_url(song.url)
            return
        if song.kugou_hash:
            self._resolve_kugou_url(song)
            return
        self._fallback_failures = 0
        self.play_failed.emit("这首歌没有可播放的音频地址")

    def _play_url(self, url: str) -> None:
        song = self.current_song
        candidates = _split_urls(url)
        if not candidates:
            self.play_failed.emit("获取音乐地址失败，请稍后重试")
            return
        self._attempted_urls = candidates
        try:
            source = proxy_url(
                candidates[0],
                fallbacks=candidates[1:],
            )
        except Exception as exc:
            self.play_failed.emit(f"在线音频代理启动失败：{exc}")
            return
        self._player.setSource(QUrl(source))
        self._player.play()
        self._pending_key = song.key if song is not None else None
        self._loading_timer.start()
        if song is not None:
            self.song_changed.emit(song)
        self._prefetch_next()

    def _resolve_kugou_url(self, song: Song) -> None:
        if self.url_resolver is None:
            self.play_failed.emit("缺少网络音源解析器")
            return
        self._resolve_serial += 1
        serial = self._resolve_serial
        self.loading_changed.emit("正在获取网络音频地址…")
        self._submit_resolve(song, self._resolve_worker, song, serial)

    def _submit_resolve(self, song: Song, fn, *args) -> None:
        key = song.key
        if key in self._resolving_keys:
            return
        self._resolving_keys.add(key)
        try:
            future = self._resolve_pool.submit(fn, *args)
        except RuntimeError:
            self._resolving_keys.discard(key)
            raise
        future.add_done_callback(
            lambda completed, k=key: self._resolving_keys.discard(k)
        )

    def _resolve_worker(
        self, song: Song, serial: int, prefetch: bool = False
    ) -> None:
        try:
            info = self.url_resolver(
                song.kugou_hash,
                force=not prefetch and self._resolve_retries > 0,
            )
        except Exception as exc:
            if prefetch:
                return
            if serial == self._resolve_serial and self.current_song is song:
                self._fallback_failures += 1
                self.play_failed.emit(str(exc))
            return
        url = (info or {}).get("url") or ""
        if not url:
            if prefetch:
                return
            if serial == self._resolve_serial and self.current_song is song:
                self._fallback_failures += 1
                self.play_failed.emit("获取音乐地址失败，请稍后重试")
            return
        backup = info.get("backup") or []
        fallbacks = list(backup) if backup else []
        if prefetch:
            self.url_prefetched.emit(song, url, fallbacks)
        else:
            self.url_ready.emit(song, url, fallbacks)

    def _on_url_ready(
        self,
        song: Song,
        url: str,
        fallbacks: Optional[List[str]],
    ) -> None:
        if self.current_song is not song:
            return
        song.url = url
        song.fallback_url = "||".join(
            candidate for candidate in (fallbacks or []) if candidate
        )
        self._failed_url_keys.clear()
        self._fallback_failures = 0
        self._play_url(song.url + ("||" + song.fallback_url if song.fallback_url else ""))

    def _on_url_prefetched(
        self,
        song: Song,
        url: str,
        fallbacks: Optional[List[str]],
    ) -> None:
        if song.url:
            return
        song.url = url
        song.fallback_url = "||".join(
            candidate for candidate in (fallbacks or []) if candidate
        )

    def _prefetch_next(self, count: int = 5) -> None:
        if self.url_resolver is None:
            return
        total = len(self._queue)
        if total <= 1 or self.repeat == REPEAT_ONE:
            return
        indices: List[int] = []
        if self.shuffle:
            choices = [i for i in range(total) if i != self._index]
            if not choices:
                return
            self._rng.shuffle(choices)
            indices = choices[:count]
        else:
            for step in range(1, count + 1):
                index = (self._index + step) % total
                if index == self._index:
                    break
                indices.append(index)
        submitted = 0
        for index in indices:
            if submitted >= count:
                break
            song = self._queue[index]
            if song.kugou_hash and not song.url and not song.local_path:
                if song.key not in self._resolving_keys:
                    self._submit_resolve(song, self._prefetch_worker, song)
                    submitted += 1

    def _prefetch_worker(self, song: Song) -> None:
        if self.url_resolver is None or song.url:
            return
        try:
            self._resolve_worker(song, 0, prefetch=True)
        except Exception:
            return

    def toggle(self) -> None:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
        else:
            if self.current_song is not None:
                self._player.play()

    def next(self) -> None:
        if not self._queue:
            return
        if self.repeat == REPEAT_ONE:
            self._restart_current()
            return
        count = len(self._queue)
        if self.shuffle and count > 1:
            choices = [i for i in range(count) if i != self._index]
            self._index = self._rng.choice(choices)
        elif self.play_mode == PLAY_MODE_ORDER and self._index >= count - 1:
            return
        else:
            self._index = (self._index + 1) % count
        self.queue_changed.emit(self.queue)
        self._start_current()

    def previous(self) -> None:
        if not self._queue:
            return
        if self._player.position() > 3000:
            self._restart_current()
            return
        count = len(self._queue)
        if self.shuffle and count > 1:
            choices = [i for i in range(count) if i != self._index]
            self._index = self._rng.choice(choices)
        elif self.play_mode == PLAY_MODE_ORDER and self._index <= 0:
            return
        else:
            self._index = (self._index - 1) % count
        self.queue_changed.emit(self.queue)
        self._start_current()

    def _restart_current(self) -> None:
        self._player.setPosition(0)
        self._player.play()

    def remove_at(self, index: int) -> None:
        if not (0 <= index < len(self._queue)):
            return
        was_current = index == self._index
        self._queue.pop(index)
        if not self._queue:
            self._index = -1
            self._player.stop()
            self.queue_changed.emit(self.queue)
            self.song_changed.emit(None)
            return
        if was_current:
            self._index = min(index, len(self._queue) - 1)
            self._start_current()
        elif index < self._index:
            self._index -= 1
        self.queue_changed.emit(self.queue)

    def clear_queue(self) -> None:
        self._queue = []
        self._index = -1
        self._pending_key = None
        self._loading_timer.stop()
        self._player.stop()
        self.queue_changed.emit(self.queue)
        self.song_changed.emit(None)

    def shutdown(self) -> None:
        self._resolve_serial += 1
        self._loading_timer.stop()
        self._position_emit.stop()
        self._player.stop()
        self._player.setSource(QUrl())
        for song in self._queue:
            song.url = ""
            song.fallback_url = ""
        self._queue = []
        self._index = -1
        self._resolving_keys.clear()
        self._failed_url_keys.clear()
        self._attempted_urls.clear()
        self._pending_key = None
        release_urls()
        try:
            self._resolve_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def set_volume(self, value: float) -> None:
        self._audio.setVolume(max(0.0, min(1.0, value)))

    def volume(self) -> float:
        return self._audio.volume()

    def set_output_device_by_id(self, device_key: str) -> None:
        """Switch the audio output device by description, falling back to the default one."""
        if device_key:
            for device in QMediaDevices.audioOutputs():
                if device.description() == device_key:
                    self._audio.setDevice(device)
                    return
        default = QMediaDevices.defaultAudioOutput()
        if not default.isNull():
            self._audio.setDevice(default)

    def seek(self, position_ms: int) -> None:
        self._player.setPosition(max(0, position_ms))

    def set_shuffle(self, enabled: bool) -> None:
        self.shuffle = enabled
        if enabled:
            self.play_mode = PLAY_MODE_SHUFFLE
        elif self.repeat == REPEAT_ONE:
            self.play_mode = PLAY_MODE_ONE
        elif self.repeat == REPEAT_ALL:
            self.play_mode = PLAY_MODE_LIST
        else:
            self.play_mode = PLAY_MODE_ORDER

    def cycle_repeat(self) -> str:
        order = [REPEAT_OFF, REPEAT_ALL, REPEAT_ONE]
        self.repeat = order[(order.index(self.repeat) + 1) % len(order)]
        if self.repeat == REPEAT_ONE:
            self.play_mode = PLAY_MODE_ONE
        elif self.repeat == REPEAT_ALL:
            self.play_mode = PLAY_MODE_LIST
        else:
            self.play_mode = PLAY_MODE_ORDER
        return self.repeat

    def set_play_mode(self, mode: str) -> None:
        self.play_mode = mode
        if mode == PLAY_MODE_ORDER:
            self.shuffle = False
            self.repeat = REPEAT_OFF
        elif mode == PLAY_MODE_LIST:
            self.shuffle = False
            self.repeat = REPEAT_ALL
        elif mode == PLAY_MODE_ONE:
            self.shuffle = False
            self.repeat = REPEAT_ONE
        elif mode == PLAY_MODE_SHUFFLE:
            self.shuffle = True
            self.repeat = REPEAT_OFF

    def _on_position_changed(self, position: int) -> None:
        self._last_position = int(position)

    def _emit_position(self) -> None:
        self.position_changed.emit(self._last_position)

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._loading_timer.stop()
            if not self._position_emit.isActive():
                self._position_emit.start()
            self.state_changed.emit("playing")
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._position_emit.stop()
            self.position_changed.emit(self._last_position)
            self.state_changed.emit("paused")
        else:
            self._position_emit.stop()
            self.position_changed.emit(self._last_position)
            self.state_changed.emit("stopped")

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.repeat == REPEAT_ONE:
                self._restart_current()
            elif self.shuffle and len(self._queue) > 1:
                self.next()
            elif self.repeat == REPEAT_ALL or self._index < len(self._queue) - 1:
                self.next()
            else:
                self._player.stop()

    def _on_loading_timeout(self) -> None:
        song = self.current_song
        if song is None or song.key != self._pending_key:
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            return

        remaining = [
            candidate
            for candidate in _split_urls(
                song.url + ("||" + song.fallback_url if song.fallback_url else "")
            )
            if candidate not in self._failed_url_keys
        ]
        if remaining:
            self._failed_url_keys.add(remaining[0])
            self._play_url(remaining[0])
            return
        if song.kugou_hash and self._resolve_retries < 3:
            self._resolve_retries += 1
            song.url = ""
            song.fallback_url = ""
            self._resolve_kugou_url(song)
            return
        self.play_failed.emit("播放缓冲超时，请检查网络后重试")

    def _on_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        song = self.current_song
        if song is None:
            self.play_failed.emit(message or "播放失败，请检查音频地址")
            return
        remaining = [
            candidate
            for candidate in _split_urls(
                song.url + ("||" + song.fallback_url if song.fallback_url else "")
            )
            if candidate not in self._failed_url_keys
        ]
        if remaining:
            self._failed_url_keys.add(remaining[0])
            self._play_url(remaining[0])
            return
        if song.kugou_hash and self._resolve_retries < 3:
            self._resolve_retries += 1
            song.url = ""
            song.fallback_url = ""
            self._resolve_kugou_url(song)
            return
        self.play_failed.emit(message or "播放失败，请检查音频地址")
