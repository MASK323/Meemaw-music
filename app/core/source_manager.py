"""Configurable music-source resolver used by Meemaw.

The original app has a very good Kugou Concept Edition resolver, but the
player only knew about that one resolver and every lookup was repeated.  This
module keeps that resolver as the default source, adds Cymusic-like user
sources (HTTP JSON endpoints), and puts a small memory/disk cache in front of
all lookups.  The public API deliberately accepts the existing ``Song``
objects so the old cover/lyric/comment/queue code remains untouched.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


_DEFAULT_SOURCE = {
    "id": "kugou_concept",
    "name": "酷狗概念版",
    "kind": "builtin",
    "enabled": True,
    "priority": 0,
    "base_url": "",
    "search_url": "",
    "resolve_url": "",
    "headers": {},
    "timeout": 4.5,
}


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_text(value: Any) -> str:
    text = _safe_text(value).lower()
    text = re.sub(r"[\[\]【】()（）{}<>《》]", " ", text)
    text = re.sub(r"\b(feat\.?|ft\.?|remix|live|现场|伴奏|纯音乐)\b", " ", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)
    return text


def song_cache_key(song: Any, quality: str | None = None) -> str:
    title = normalize_text(getattr(song, "title", ""))
    artist = normalize_text(getattr(song, "artist", ""))
    album = normalize_text(getattr(song, "album", ""))
    track_id = _safe_text(getattr(song, "track_id", ""))
    return "|".join((title, artist, album, track_id, _safe_text(quality or "")))


def _iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _is_playable_url(candidate: str) -> bool:
    """Reject the common non-audio URLs returned beside an API result."""
    if not isinstance(candidate, str) or not candidate.startswith(("http://", "https://", "file://")):
        return False
    return not re.search(
        r"\.(?:jpg|jpeg|png|gif|webp|bmp|svg|lrc|txt|json|html?)(?:$|[?#])",
        candidate,
        re.I,
    ) and not re.search(r"(?:cover|album.?art|lyrics?|lyric|pic(?:ture)?)(?:[=/._-]|$)", candidate, re.I)


def _first_url(value: Any) -> str:
    """Extract a playable URL from common API response shapes."""
    if _is_playable_url(value):
        return value
    url_keys = ("url", "play_url", "playUrl", "audio", "src", "uri", "musicUrl", "downloadUrl")
    for item in _iter_dicts(value):
        for key in url_keys:
            candidate = item.get(key)
            if _is_playable_url(candidate):
                return candidate
    return ""


def _all_urls(value: Any) -> list[str]:
    found: list[str] = []
    if _is_playable_url(value):
        found.append(value)
    for item in _iter_dicts(value):
        for key in ("url", "play_url", "playUrl", "audio", "src", "uri", "musicUrl", "downloadUrl", "backupUrl"):
            candidate = item.get(key)
            if _is_playable_url(candidate) and candidate not in found:
                found.append(candidate)
    return found


def _endpoint(
    template: str,
    song: Any,
    quality: str | None = None,
    *,
    overrides: dict[str, Any] | None = None,
    append_keyword: bool = False,
) -> str:
    title = _safe_text(getattr(song, "title", ""))
    artist = _safe_text(getattr(song, "artist", ""))
    album = _safe_text(getattr(song, "album", ""))
    track_id = _safe_text(getattr(song, "track_id", ""))
    keyword = " ".join(part for part in (title, artist) if part)
    values = {
        "title": title,
        "artist": artist,
        "album": album,
        "id": track_id,
        "keyword": keyword,
        "quality": _safe_text(quality or "320"),
    }
    if overrides:
        values.update({key: _safe_text(value) for key, value in overrides.items()})
    try:
        endpoint = template.format(**{k: urllib.parse.quote(v) for k, v in values.items()})
    except (KeyError, ValueError):
        endpoint = template
    if append_keyword and endpoint and "{" not in template:
        # A plain base URL is a valid custom source too. Make it useful by
        # sending the normalized source contract without disturbing an
        # already-configured query string.
        parsed = urllib.parse.urlsplit(endpoint)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower() in {"keyword", "q", "query", "name", "search"} for key, _ in query):
            query.append(("keyword", keyword))
            endpoint = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
            )
    return endpoint


def _http_json(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
        raw = response.read()
    text = raw.decode("utf-8", "replace").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_text": text}


@dataclass
class AudioSource:
    id: str
    name: str
    kind: str = "http"
    enabled: bool = True
    priority: int = 50
    base_url: str = ""
    search_url: str = ""
    resolve_url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 4.5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AudioSource":
        raw = dict(data or {})
        source = dict(_DEFAULT_SOURCE)
        source.update(raw)
        # Custom sources should be optional fallbacks by default. The built-in
        # Kugou Concept source stays priority 0; callers can explicitly choose
        # a lower custom priority when they want to make it primary.
        if source.get("id") != "kugou_concept" and "priority" not in raw:
            source["priority"] = 50
        source["id"] = _safe_text(source.get("id")) or "source"
        source["name"] = _safe_text(source.get("name")) or source["id"]
        source["headers"] = dict(source.get("headers") or {})
        try:
            source["priority"] = int(source.get("priority", 50))
        except (TypeError, ValueError):
            source["priority"] = 50
        try:
            source["timeout"] = max(1.0, min(15.0, float(source.get("timeout", 4.5))))
        except (TypeError, ValueError):
            source["timeout"] = 4.5
        return cls(**{key: source[key] for key in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceManager:
    """Persistent source list plus fast, de-duplicated URL resolution."""

    CACHE_TTL = 60 * 60 * 8
    CACHE_LIMIT = 512

    def __init__(self, config_path: str | os.PathLike[str] | None = None) -> None:
        self._lock = threading.RLock()
        self._inflight: dict[str, threading.Event] = {}
        self._memory_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._failure_until: dict[str, float] = {}
        self._config_path = Path(config_path) if config_path else self._default_config_path()
        self._sources: list[AudioSource] = []
        self._disk_cache: dict[str, dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _default_config_path() -> Path:
        override = os.environ.get("MEEMAW_CONFIG_DIR")
        if override:
            root = Path(override)
        elif os.name == "nt" and os.environ.get("APPDATA"):
            root = Path(os.environ["APPDATA"]) / "MeemawMusic"
        else:
            root = Path.home() / ".config" / "meemaw-music"
        return root / "audio_sources.json"

    def _load(self) -> None:
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}
        raw_sources = payload.get("sources") if isinstance(payload, dict) else None
        if not isinstance(raw_sources, list):
            raw_sources = [_DEFAULT_SOURCE]
        sources: list[AudioSource] = []
        seen: set[str] = set()
        for raw in raw_sources:
            if not isinstance(raw, dict):
                continue
            # The built-in Kugou Concept resolver is application-owned.
            if raw.get("id") == "kugou_concept":
                source = AudioSource.from_dict(_DEFAULT_SOURCE)
                if source.id not in seen:
                    seen.add(source.id)
                    sources.append(source)
                continue
            if "kind" not in raw:
                raw = {**raw, "kind": "http"}
            source = AudioSource.from_dict(raw)
            if source.id in seen:
                continue
            seen.add(source.id)
            sources.append(source)
        builtin = next((item for item in sources if item.id == "kugou_concept"), None)
        if builtin is None:
            builtin = AudioSource.from_dict(_DEFAULT_SOURCE)
        # Keep the guaranteed built-in source at the top of the list even if
        # an older config file stored custom sources before it.
        self._sources = [builtin] + [item for item in sources if item.id != "kugou_concept"]
        raw_cache = payload.get("cache") if isinstance(payload, dict) else None
        if isinstance(raw_cache, dict):
            now = time.time()
            self._disk_cache = {
                key: value for key, value in raw_cache.items()
                if isinstance(value, dict) and now - float(value.get("time", 0) or 0) < self.CACHE_TTL
            }

    def _save(self) -> None:
        payload = {"version": 1, "sources": [source.to_dict() for source in self._sources], "cache": self._disk_cache}
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._config_path.with_suffix(self._config_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self._config_path)
        except OSError:
            # Portable mode or read-only installations must not stop playback.
            pass

    def sources(self) -> list[AudioSource]:
        with self._lock:
            return [AudioSource.from_dict(source.to_dict()) for source in self._sources]

    def enabled_sources(self) -> list[AudioSource]:
        return sorted((source for source in self.sources() if source.enabled), key=lambda item: (item.priority, item.id))

    def get(self, source_id: str) -> AudioSource | None:
        with self._lock:
            for source in self._sources:
                if source.id == source_id:
                    return AudioSource.from_dict(source.to_dict())
        return None

    def upsert(self, data: dict[str, Any] | AudioSource) -> AudioSource:
        if isinstance(data, AudioSource):
            source = data
        else:
            raw = dict(data or {})
            if raw.get("id") != "kugou_concept" and "kind" not in raw:
                raw["kind"] = "http"
            source = AudioSource.from_dict(raw)
        if source.id == "kugou_concept":
            # Never accept caller-provided fields for the built-in source.
            return AudioSource.from_dict(_DEFAULT_SOURCE)
        with self._lock:
            for index, old in enumerate(self._sources):
                if old.id == source.id:
                    self._sources[index] = source
                    break
            else:
                self._sources.append(source)
            self._memory_cache.clear()
            self._disk_cache.clear()
            self._save()
        return source

    def remove(self, source_id: str) -> bool:
        if source_id == "kugou_concept":
            return False
        with self._lock:
            before = len(self._sources)
            self._sources = [source for source in self._sources if source.id != source_id]
            changed = len(self._sources) != before
            if changed:
                self._memory_cache.clear()
                self._disk_cache.clear()
                self._save()
            return changed

    def set_enabled(self, source_id: str, enabled: bool) -> bool:
        if source_id == "kugou_concept":
            # It is the guaranteed fallback and is permanently enabled.
            return False
        with self._lock:
            source = next((item for item in self._sources if item.id == source_id), None)
            if source is None:
                return False
            source.enabled = bool(enabled)
            # Never leave the app with no usable source.
            if not source.enabled and not any(item.enabled for item in self._sources):
                source.enabled = True
            self._memory_cache.clear()
            self._disk_cache.clear()
            self._save()
            return True

    def clear_cache(self, song: Any | None = None, quality: str | None = None) -> None:
        """Invalidate all, or one song/quality, URL cache entries."""
        with self._lock:
            if song is None:
                self._memory_cache.clear()
                self._disk_cache.clear()
            else:
                key = song_cache_key(song, quality)
                self._memory_cache.pop(key, None)
                self._disk_cache.pop(key, None)
            self._save()

    def reset_defaults(self) -> None:
        with self._lock:
            self._sources = [AudioSource.from_dict(_DEFAULT_SOURCE)]
            self._memory_cache.clear()
            self._disk_cache.clear()
            self._save()

    @staticmethod
    def _result_from_payload(payload: Any) -> dict[str, Any] | None:
        urls = _all_urls(payload)
        if not urls:
            return None
        return {"url": urls[0], "backup": urls[1:8]}

    def _resolve_http(self, source: AudioSource, song: Any, quality: str | None) -> dict[str, Any] | None:
        headers = {"User-Agent": "MeemawMusic/1.0", **source.headers}
        search_url = _endpoint(
            source.search_url or source.base_url,
            song,
            quality,
            append_keyword=True,
        )
        payload: Any = None
        if search_url:
            try:
                payload = _http_json(search_url, headers, source.timeout)
            except (OSError, ValueError, urllib.error.URLError):
                payload = None
        result = self._result_from_payload(payload)
        if result:
            return result
        # Common two-stage source: search returns an id, resolve endpoint
        # returns the playable URL.  The configured {id} is filled from the
        # first id-like value in the search response when possible.
        if source.resolve_url:
            identifier = ""
            for item in _iter_dicts(payload) if payload is not None else ():
                for key in ("id", "songmid", "songId", "track_id", "hash"):
                    if item.get(key) is not None:
                        identifier = _safe_text(item[key])
                        break
                if identifier:
                    break
            if identifier:
                resolve_url = _endpoint(
                    source.resolve_url,
                    song,
                    quality,
                    overrides={"id": identifier},
                )
            else:
                resolve_url = _endpoint(source.resolve_url, song, quality)
            try:
                result = self._result_from_payload(_http_json(resolve_url, headers, source.timeout))
            except (OSError, ValueError, urllib.error.URLError):
                result = None
        return result

    def _resolve_one(self, source: AudioSource, song: Any, builtin_resolver: Callable[..., Any] | None, quality: str | None, force: bool) -> dict[str, Any] | None:
        if source.kind == "builtin":
            if not builtin_resolver or not getattr(song, "kugou_hash", ""):
                return None
            info = builtin_resolver(getattr(song, "kugou_hash", ""), quality=quality, force=force)
            if not isinstance(info, dict):
                return None
            url = _safe_text(info.get("url"))
            if not url:
                return None
            return {"url": url, "backup": list(info.get("backup") or []), "source": source.id}
        return self._resolve_http(source, song, quality)

    def resolve_song(self, song: Any, builtin_resolver: Callable[..., Any] | None, quality: str | None = None, force: bool = False) -> dict[str, Any] | None:
        key = song_cache_key(song, quality)
        now = time.time()
        if force:
            # A forced retry must not replay a stale URL from a previous source.
            with self._lock:
                self._memory_cache.pop(key, None)
                self._disk_cache.pop(key, None)
        if not force:
            with self._lock:
                memory = self._memory_cache.get(key)
                if memory and now - memory[0] < self.CACHE_TTL:
                    return dict(memory[1])
                disk = self._disk_cache.get(key)
                if disk and now - float(disk.get("time", 0) or 0) < self.CACHE_TTL and disk.get("url"):
                    result = dict(disk)
                    self._memory_cache[key] = (now, result)
                    return result
                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._inflight[key] = event
                    owner = True
                else:
                    owner = False
            if not owner:
                event.wait(8.0)
                with self._lock:
                    cached = self._memory_cache.get(key)
                    return dict(cached[1]) if cached else None
        else:
            owner = True
            event = None

        try:
            sources = self.enabled_sources()
            result: dict[str, Any] | None = None
            # Resolve same-priority sources concurrently; lower priority acts
            # as a fallback.  This is faster than waiting through every source
            # serially while still making priority meaningful.
            for priority in sorted({source.priority for source in sources}):
                group = [source for source in sources if source.priority == priority]
                with ThreadPoolExecutor(max_workers=min(4, max(1, len(group))), thread_name_prefix="mm-source") as pool:
                    futures = [pool.submit(self._resolve_one, source, song, builtin_resolver, quality, force) for source in group]
                    for future in as_completed(futures):
                        try:
                            candidate = future.result()
                        except Exception:
                            candidate = None
                        if candidate and candidate.get("url"):
                            result = candidate
                            break
                    for future in futures:
                        if not future.done():
                            future.cancel()
                if result:
                    break
            if result:
                with self._lock:
                    self._memory_cache[key] = (now, result)
                    self._disk_cache[key] = {"time": now, **result}
                    if len(self._memory_cache) > self.CACHE_LIMIT:
                        oldest = min(self._memory_cache, key=lambda item: self._memory_cache[item][0])
                        self._memory_cache.pop(oldest, None)
                    if len(self._disk_cache) > self.CACHE_LIMIT:
                        oldest = min(self._disk_cache, key=lambda item: float(self._disk_cache[item].get("time", 0) or 0))
                        self._disk_cache.pop(oldest, None)
                    self._save()
            return result
        finally:
            if not force:
                with self._lock:
                    active = self._inflight.pop(key, None)
                    if active:
                        active.set()

    def test_source(self, source_id: str) -> tuple[bool, str]:
        source = self.get(source_id)
        if source is None:
            return False, "音源不存在"
        if source.kind == "builtin":
            return True, "默认酷狗概念版音源由登录态与歌曲匹配时测试"
        if not source.search_url and not source.base_url:
            return False, "未填写搜索地址"
        class Probe:
            title = "晴天"
            artist = "周杰伦"
            album = ""
            track_id = ""
        try:
            result = self._resolve_http(source, Probe(), "320")
            return (True, "音源可用") if result else (False, "接口未返回可播放地址")
        except Exception as exc:
            return False, str(exc)


_default_manager: SourceManager | None = None
_default_lock = threading.Lock()


def get_source_manager() -> SourceManager:
    global _default_manager
    with _default_lock:
        if _default_manager is None:
            _default_manager = SourceManager()
        return _default_manager


__all__ = [
    "AudioSource",
    "SourceManager",
    "get_source_manager",
    "normalize_text",
    "song_cache_key",
]
