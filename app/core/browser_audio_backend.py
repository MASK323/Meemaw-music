"""Chromium HTMLAudioElement backend for the Meemaw player.

This module deliberately uses a hidden Qt WebEngine page and the browser's
HTMLAudioElement, matching the playback path used by MoeKoe.  It exposes the
small QMediaPlayer-shaped surface used by the existing UI so queue and UI code
can remain unchanged while the network/decoder path is replaced.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    path = Path(__file__).resolve()
    # In the frozen app this module lives at <root>/app/core; during source
    # tests it may live directly in patch_src, so do not assume three parents.
    return path.parents[3] if len(path.parents) > 3 else path.parent


# Qt WebEngine looks for its subprocess beside the PySide6 runtime.  Set this
# before importing the WebEngine bindings so it also works in the frozen app.
_root = _runtime_root()
for _candidate in (_root / "PySide6" / "QtWebEngineProcess.exe", _root / "QtWebEngineProcess.exe"):
    if _candidate.exists():
        os.environ.setdefault("QTWEBENGINEPROCESS_PATH", str(_candidate))
        break

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"></head><body>
<script>
(() => {
  const audio = new Audio();
  // Do not request anonymous CORS mode here.  Kugou's signed CDN URLs are intended for
  // direct media playback and commonly omit Access-Control-Allow-Origin.
  // Setting anonymous makes Chromium reject an otherwise valid MP3 before it
  // can be decoded, which presents as a silent/empty player.
  audio.preload = "auto";
  audio.playsInline = true;
  window.__mmAudio = audio;
  window.__mmState = "stopped";
  window.__mmError = "";
  window.__mmEnded = false;

  const clearError = () => { window.__mmError = ""; };
  audio.addEventListener("playing", () => { window.__mmState = "playing"; clearError(); });
  audio.addEventListener("play", () => { window.__mmState = "playing"; });
  audio.addEventListener("pause", () => {
    if (!audio.ended) window.__mmState = "paused";
  });
  audio.addEventListener("ended", () => {
    window.__mmState = "stopped";
    window.__mmEnded = true;
  });
  audio.addEventListener("error", () => {
    const e = audio.error;
    window.__mmState = "stopped";
    window.__mmError = e ? (e.message || ("HTMLMediaError " + e.code)) : "HTML audio error";
  });
  audio.addEventListener("abort", () => {
    if (!audio.ended) window.__mmState = "stopped";
  });

  window.__mmSetSource = (url) => {
    window.__mmEnded = false;
    clearError();
    window.__mmState = "stopped";
    audio.pause();
    const value = String(url || "").trim();
    if (!value) {
      audio.removeAttribute("src");
      window.__mmError = "音频地址为空";
      return;
    }
    // Assign the URL directly to HTMLAudioElement.  This preserves the CDN's
    // signed query string and avoids an XHR/CORS preflight.
    audio.src = value;
    audio.load();
  };
  window.__mmPlay = () => {
    if (!audio.src) {
      window.__mmState = "stopped";
      window.__mmError = "音频地址为空";
      return Promise.resolve(false);
    }
    return audio.play().then(() => {
      window.__mmState = "playing";
      return true;
    }).catch((e) => {
      window.__mmState = "stopped";
      const code = audio.error && audio.error.code ? (" (code " + audio.error.code + ")") : "";
      window.__mmError = (e && e.message ? e.message : String(e)) + code;
      return false;
    });
  };
  window.__mmPause = () => { audio.pause(); window.__mmState = "paused"; };
  window.__mmStop = () => {
    audio.pause();
    try { audio.currentTime = 0; } catch (_) {}
    window.__mmState = "stopped";
  };
  window.__mmSeek = (ms) => {
    const seconds = Math.max(0, Number(ms || 0) / 1000);
    if (Number.isFinite(seconds)) {
      try { audio.currentTime = seconds; } catch (_) {}
    }
  };
  window.__mmVolume = (value) => {
    audio.volume = Math.max(0, Math.min(1, Number(value || 0)));
  };
  window.__mmSetPlaybackRate = (value) => {
    const rate = Number(value);
    if (Number.isFinite(rate)) {
      audio.playbackRate = Math.max(0.25, Math.min(4, rate));
    }
  };
})();
</script></body></html>"""


class BrowserAudioAdapter(QObject):
    """A QMediaPlayer-compatible adapter backed by Chromium HTML audio."""

    playbackStateChanged = Signal(object)
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playbackRateChanged = Signal(float)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)
    ended = Signal()
    ready = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._view = QWebEngineView()
        self._view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._view.resize(2, 2)
        self._view.hide()
        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )

        self._state = QMediaPlayer.PlaybackState.StoppedState
        self._position_ms = 0
        self._duration_ms = 0
        self._volume = 1.0
        self._playback_rate = 1.0
        self._source = ""
        self._ready = False
        self._pending_play = False
        self._last_error = ""
        self._last_ended = False
        self._js_queue: list[str] = []

        self._view.loadFinished.connect(self._on_loaded)
        self._view.setHtml(_HTML, QUrl("file:///meemaw_audio.html"))
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _run(self, expression: str) -> None:
        if not self._ready:
            self._js_queue.append(expression)
            return
        try:
            self._view.page().runJavaScript(expression)
        except RuntimeError:
            # The page may be shutting down; no playback operation should take
            # the whole application down with it.
            pass

    def _on_loaded(self, ok: bool) -> None:
        self._ready = bool(ok)
        self.ready.emit(bool(ok))
        if not ok:
            self._emit_error("Chromium audio page failed to load")
            return
        queued, self._js_queue = self._js_queue, []
        for expression in queued:
            self._run(expression)
        self._run(f"window.__mmVolume({self._volume!r})")
        self._run(f"window.__mmSetPlaybackRate({self._playback_rate!r})")
        if self._pending_play:
            self._pending_play = False
            self._run("window.__mmPlay()")

    def _emit_state(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == self._state:
            return
        self._state = state
        self.playbackStateChanged.emit(state)

    def _emit_error(self, message: str) -> None:
        message = str(message or "HTML audio playback failed")
        if message == self._last_error:
            return
        self._last_error = message
        self.errorOccurred.emit(QMediaPlayer.Error.ResourceError, message)

    def _poll(self) -> None:
        if not self._ready:
            return
        expression = (
            "JSON.stringify({state:window.__mmState, position:window.__mmAudio.currentTime, "
            "duration:window.__mmAudio.duration, error:window.__mmError, ended:window.__mmEnded})"
        )
        try:
            self._view.page().runJavaScript(expression, self._on_poll_result)
        except RuntimeError:
            pass

    @Slot(object)
    def _on_poll_result(self, value: Any) -> None:
        if not value:
            return
        try:
            data = json.loads(value) if isinstance(value, str) else value
            position = float(data.get("position") or 0.0)
            duration = float(data.get("duration") or 0.0)
            position_ms = max(0, int(position * 1000))
            duration_ms = max(0, int(duration * 1000))
        except (TypeError, ValueError, json.JSONDecodeError):
            return

        if position_ms != self._position_ms:
            self._position_ms = position_ms
            self.positionChanged.emit(position_ms)
        if duration_ms != self._duration_ms:
            self._duration_ms = duration_ms
            self.durationChanged.emit(duration_ms)

        state = str(data.get("state") or "stopped")
        mapped = {
            "playing": QMediaPlayer.PlaybackState.PlayingState,
            "paused": QMediaPlayer.PlaybackState.PausedState,
            "stopped": QMediaPlayer.PlaybackState.StoppedState,
        }.get(state, QMediaPlayer.PlaybackState.StoppedState)
        self._emit_state(mapped)

        error = str(data.get("error") or "")
        if error:
            self._emit_error(error)
        else:
            self._last_error = ""

        ended = bool(data.get("ended"))
        if ended and not self._last_ended:
            self.ended.emit()
        self._last_ended = ended

    def setSource(self, source: QUrl | str) -> None:
        self._source = source.toString() if isinstance(source, QUrl) else str(source)
        self._position_ms = 0
        self._duration_ms = 0
        self._last_ended = False
        self._last_error = ""
        self._run(f"window.__mmSetSource({json.dumps(self._source)})")

    def play(self) -> None:
        self._pending_play = not self._ready
        self._run("window.__mmPlay()")

    def pause(self) -> None:
        self._pending_play = False
        self._run("window.__mmPause()")

    def stop(self) -> None:
        self._pending_play = False
        self._run("window.__mmStop()")
        self._emit_state(QMediaPlayer.PlaybackState.StoppedState)

    def setPosition(self, position_ms: int) -> None:
        self._position_ms = max(0, int(position_ms))
        self._run(f"window.__mmSeek({self._position_ms})")
        self.positionChanged.emit(self._position_ms)

    def position(self) -> int:
        return self._position_ms

    def duration(self) -> int:
        return self._duration_ms

    def playbackState(self) -> QMediaPlayer.PlaybackState:
        return self._state

    def setVolume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))
        self._run(f"window.__mmVolume({self._volume!r})")

    def volume(self) -> float:
        return self._volume

    def setPlaybackRate(self, rate: float) -> None:
        # Chromium's HTMLAudioElement supports rates from 0.25x to 4x.  Keep
        # the UI's normal range inside that limit and retain the value across
        # source changes, just like MoeKoe's persistent Audio element.
        try:
            value = float(rate)
        except (TypeError, ValueError):
            return
        value = max(0.25, min(4.0, value))
        if value == self._playback_rate:
            self._run(f"window.__mmSetPlaybackRate({value!r})")
            return
        self._playback_rate = value
        self._run(f"window.__mmSetPlaybackRate({value!r})")
        self.playbackRateChanged.emit(value)

    def playbackRate(self) -> float:
        return self._playback_rate

    def close(self) -> None:
        self._poll_timer.stop()
        self._view.deleteLater()


# Keep this import-free helper in the backend so player_wrapper.py only has to
# replace the class and does not need to duplicate the queue implementation.
def patch_player_manager(original_class: type) -> type:
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QMediaPlayer

    class BrowserPlayerManager(original_class):
        """Original queue manager with MoeKoe's browser audio transport."""

        def __init__(self, parent=None):
            super().__init__(parent)
            # URL lookup is kept behind a source manager so the default Kugou
            # Concept resolver remains first-class while user sources can be
            # enabled as fast fallbacks without changing Song objects or the
            # existing cover/lyrics/comment queue pipeline.
            from app.core.source_manager import get_source_manager
            self._source_manager = get_source_manager()
            # Keep the old object alive only through its Qt parent; all new
            # playback operations are directed to Chromium below.
            old_player = self._player
            self._browser_audio = BrowserAudioAdapter(self)
            self._player = self._browser_audio

            # The original manager's timers and recovery callbacks are tied to
            # QMediaPlayer status.  They are all disabled: Chromium owns the
            # media buffering/error state, and mixing the old 5/8/15 second
            # timers back in would recreate the original false-stall problem.
            for name in (
                "_loading_timer",
                "_stall_timer",
                "_resume_timer",
                "_auto_resume_timer",
                "_watchdog_timer",
                "_position_emit",
            ):
                timer = getattr(self, name, None)
                if timer is not None:
                    timer.stop()
            # No source is ever sent to the obsolete Qt multimedia player.
            # Release it after the inherited signal wiring has completed.
            try:
                old_player.deleteLater()
            except RuntimeError:
                pass

            self._browser_audio.playbackStateChanged.connect(self._on_state_changed)
            self._browser_audio.positionChanged.connect(self._on_position_changed)
            self._browser_audio.durationChanged.connect(self.duration_changed.emit)
            self._browser_audio.ended.connect(self._browser_ended)
            self._browser_audio.errorOccurred.connect(self._browser_error)

        def _resolve_worker(self, song, serial: int, prefetch: bool = False):
            """Resolve through configurable sources while preserving old signals."""
            from app.core.source_manager import get_source_manager

            manager = getattr(self, "_source_manager", None) or get_source_manager()
            self._source_manager = manager
            try:
                # Prefetch must never force a network refresh. Active retries
                # use the original retry counter, and SourceManager clears the
                # per-song cache before a forced lookup.
                force = (not prefetch) and getattr(self, "_resolve_retries", 0) > 0
                info = manager.resolve_song(
                    song,
                    builtin_resolver=getattr(self, "url_resolver", None),
                    quality=None,
                    force=force,
                )
                info = info if isinstance(info, dict) else {}
                url = str(info.get("url") or "")
                if not url:
                    if prefetch:
                        return
                    if serial == getattr(self, "_resolve_serial", -1) and self.current_song is song:
                        self._fallback_failures += 1
                        self.play_failed.emit("获取音乐地址失败，请稍后重试")
                    return
                fallbacks = list(info.get("backup") or [])
                if prefetch:
                    self.url_prefetched.emit(song, url, fallbacks)
                else:
                    self.url_ready.emit(song, url, fallbacks)
            except Exception as exc:
                # A broken custom source must behave exactly like a failed
                # optional fallback, not take down playback or the UI thread.
                if (not prefetch and serial == getattr(self, "_resolve_serial", -1)
                        and self.current_song is song):
                    self._fallback_failures += 1
                    self.play_failed.emit(str(exc) or "获取音乐地址失败，请稍后重试")

        def _play_url(self, url: str, song=None):
            # Keep the original PlayerManager contract.  _on_url_ready() calls
            # this method with only the URL; the original implementation then
            # obtains the active Song from current_song.  If we leave song as
            # None here, song_changed is never emitted and the existing cover,
            # lyrics, comments, and now-playing views cannot refresh.
            # The original method intentionally ignores its optional
            # argument and always uses the queue's active item.  URL resolution
            # calls _play_url(combined_url) without a Song argument; using a
            # stale/None argument here drops song_changed and therefore breaks
            # cover, lyrics, comments, and the now-playing page.
            song = self.current_song

            # Same URL/cross-origin semantics as MoeKoe: use the first fresh
            # URL returned by /song/url, without a QMediaPlayer loading timer.
            from app.core._player_original import _split_urls

            candidates = _split_urls(url)
            if not candidates:
                self.play_failed.emit("获取音乐地址失败，请稍后重试")
                return
            self._attempted_urls = candidates
            self._current_audio_url = candidates[0]
            self._player.setSource(QUrl(candidates[0]))
            self._player.play()
            self._pending_key = song.key if song is not None else None
            if song is not None:
                self.song_changed.emit(song)
            self._prefetch_next()

        def _on_state_changed(self, state):
            """Forward browser state without the old Qt recovery state machine."""
            if state == QMediaPlayer.PlaybackState.PlayingState:
                value = "playing"
            elif state == QMediaPlayer.PlaybackState.PausedState:
                value = "paused"
            else:
                value = "stopped"
            self.state_changed.emit(value)

        def _on_position_changed(self, position):
            """Publish browser time directly; do not run the stall timer."""
            current = int(position)
            self._last_position = current
            self._stream_stall_count = 0
            self.position_changed.emit(current)

        def _browser_ended(self):
            # Reuse only the queue/end-of-media policy; no network recovery
            # state machine is involved.
            self._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)

        def _browser_error(self, error, message: str):
            # Browser errors are real errors. Try the existing alternate URL /
            # forced re-resolution path once, instead of ignoring errors while
            # Qt reports a stale PlayingState.
            try:
                self._try_fallback_or_reresolve(self._browser_audio.position())
            except Exception:
                self.play_failed.emit(message or "播放失败")

        def set_volume(self, value: float):
            self._browser_audio.setVolume(value)

        def set_playback_rate(self, rate: float):
            self._browser_audio.setPlaybackRate(rate)

        def playback_rate(self) -> float:
            return self._browser_audio.playbackRate()

        def set_speed(self, rate: float):
            # Alias for integrations that call the feature "speed".
            self.set_playback_rate(rate)

        def speed(self) -> float:
            return self.playback_rate()

        def volume(self) -> float:
            # Keep the original PlayerManager API: callers invoke volume().
            return self._browser_audio.volume()

        def shutdown(self):
            try:
                self._browser_audio.close()
            finally:
                return super().shutdown()

    BrowserPlayerManager.__name__ = "PlayerManager"
    BrowserPlayerManager.__qualname__ = "PlayerManager"
    BrowserPlayerManager.__module__ = original_class.__module__
    return BrowserPlayerManager

