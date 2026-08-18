from __future__ import annotations

import atexit
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import Song

NETEASE_RANK_LIST_URL = "https://music.163.com/api/toplist/detail"
NETEASE_RANK_SONGS_URL = "https://music.163.com/api/playlist/detail"
NETEASE_SEARCH_URL = "https://music.163.com/api/search/get/web"
NETEASE_COMMENT_URL = "https://music.163.com/api/v1/resource/comments/R_SO_4_{track_id}"
KUGOU_MOBILE_SEARCH_URL = "http://mobilecdn.kugou.com/api/v3/search/song"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
    "Accept": "application/json,text/plain,*/*",
}

_SEPARATORS = re.compile(r"[、&/&\s]+")
_PUNCT = re.compile(
    r"[\s()\[\]{}（）【】《》〈〉<>·,，.。!！?？:：;；\"'“”‘’\-—–…~～]+"
)

_CACHE: Dict[str, Tuple[float, Any, float]] = {}
_CACHE_LOCK = threading.Lock()
_RANK_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="mm-net")
_SEARCH_SEMAPHORE = threading.BoundedSemaphore(12)
_SEARCH_INFLIGHT_LOCK = threading.Lock()
_SEARCH_INFLIGHT: Dict[Tuple[Any, ...], Tuple[threading.Event, Optional[Song]]] = {}

_MATCH_CACHE_PATH = (
    Path(os.environ.get("APPDATA") or str(Path.home()))
    / "MeemawMusic"
    / "kugou_match_cache.json"
)
_PERSISTENT_MATCHES: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
_PERSIST_LOCK = threading.Lock()
_LAST_MATCH_SAVE = 0.0
_MATCH_SAVE_INTERVAL = 2.0
_PERSIST_WRITER: Optional[threading.Thread] = None
_PERSIST_DIRTY = False
_PERSIST_RELEASED = False


def _cache_get(key: str) -> Tuple[bool, Any]:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is not None and time.time() - entry[0] < entry[2]:
            return True, entry[1]
    return False, None


def _song_to_payload(song: Song) -> Dict[str, Any]:
    return {
        "title": song.title,
        "artist": song.artist,
        "album": song.album,
        "duration": float(song.duration or 0),
        "cover_url": song.cover_url or "",
        "kugou_hash": song.kugou_hash or "",
        "source": song.source,
    }


def _song_from_payload(payload: Dict[str, Any]) -> Optional[Song]:
    if not isinstance(payload, dict) or not payload.get("kugou_hash"):
        return None
    return Song(
        title=str(payload.get("title") or "未知歌曲"),
        artist=str(payload.get("artist") or "未知歌手"),
        album=str(payload.get("album") or ""),
        duration=float(payload.get("duration") or 0),
        cover_url=str(payload.get("cover_url") or ""),
        kugou_hash=str(payload.get("kugou_hash") or ""),
        source=str(payload.get("source") or "来源于网络"),
    )


def _save_match_cache() -> None:
    try:
        _MATCH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _PERSIST_LOCK:
            data = {
                json.dumps(key, ensure_ascii=False): payload
                for key, payload in _PERSISTENT_MATCHES.items()
            }
        with open(_MATCH_CACHE_PATH, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


def _request_match_cache_save() -> None:
    global _PERSIST_DIRTY, _PERSIST_WRITER
    with _PERSIST_LOCK:
        if _PERSIST_RELEASED:
            return
        _PERSIST_DIRTY = True
        if _PERSIST_WRITER is not None and _PERSIST_WRITER.is_alive():
            return

        def writer() -> None:
            global _PERSIST_DIRTY
            while True:
                with _PERSIST_LOCK:
                    if _PERSIST_RELEASED:
                        return
                    dirty = _PERSIST_DIRTY
                    if not dirty:
                        return
                    _PERSIST_DIRTY = False
                _save_match_cache()
                time.sleep(1.0)

        _PERSIST_WRITER = threading.Thread(
            target=writer, name="mm-match-save", daemon=True
        )
        _PERSIST_WRITER.start()


def _maybe_save_match_cache() -> None:
    global _LAST_MATCH_SAVE
    now = time.time()
    if now - _LAST_MATCH_SAVE < _MATCH_SAVE_INTERVAL:
        return
    _LAST_MATCH_SAVE = now
    _request_match_cache_save()


def release_caches() -> None:
    """Drop in-memory sync caches and cache files on real exit."""
    global _LAST_MATCH_SAVE, _PERSIST_DIRTY, _PERSIST_RELEASED, _PERSIST_WRITER
    with _PERSIST_LOCK:
        writer = _PERSIST_WRITER
        _PERSIST_DIRTY = True
        _PERSIST_RELEASED = True
    if writer is not None:
        writer.join(timeout=2.0)
    with _CACHE_LOCK:
        _CACHE.clear()
    with _PERSIST_LOCK:
        _PERSISTENT_MATCHES.clear()
        _PERSIST_DIRTY = False
        _PERSIST_WRITER = None
    _LAST_MATCH_SAVE = 0.0
    _delete_match_cache_file()


def _delete_match_cache_file() -> None:
    for path in (
        _MATCH_CACHE_PATH,
        Path(str(_MATCH_CACHE_PATH) + ".tmp"),
    ):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _load_match_cache() -> None:
    try:
        if not _MATCH_CACHE_PATH.exists():
            return
        raw = json.loads(_MATCH_CACHE_PATH.read_text(encoding="utf-8") or "{}")
        now = time.time()
        migrated: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        with _CACHE_LOCK:
            for key_text, payload in raw.items():
                try:
                    key = tuple(json.loads(key_text))
                except Exception:
                    continue
                if len(key) == 4 and key[0] == "kugou_search":
                    try:
                        duration = float(key[3])
                    except (TypeError, ValueError):
                        duration = 0.0
                    key = (key[0], key[1], key[2], int(duration // 5.0) * 5)
                if isinstance(payload, dict) and payload.get("failed"):
                    _CACHE[key] = (now, None, 900.0)
                    migrated[key] = payload
                    continue
                song = _song_from_payload(payload)
                if song is None:
                    continue
                _CACHE[key] = (now, song, 1800.0)
                migrated[key] = payload
        with _PERSIST_LOCK:
            _PERSISTENT_MATCHES.update(migrated)
    except Exception:
        pass


_load_match_cache()


def _save_match_cache_atexit() -> None:
    with _PERSIST_LOCK:
        if _PERSIST_RELEASED:
            return
    _save_match_cache()


atexit.register(_save_match_cache_atexit)


def _cache_set(key: str, value: Any, ttl: float = 1800.0, limit: int = 512) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value, ttl)
        if len(_CACHE) > limit:
            oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
            del _CACHE[oldest]
    if isinstance(key, tuple) and key and key[0] == "kugou_search":
        with _PERSIST_LOCK:
            if isinstance(value, Song) and value.kugou_hash:
                _PERSISTENT_MATCHES[key] = _song_to_payload(value)
            elif value is None:
                _PERSISTENT_MATCHES[key] = {"failed": True}
        _maybe_save_match_cache()


def _https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _normalize(text: str) -> str:
    return _PUNCT.sub("", text or "").strip().lower()


def _http_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    retries: int = 3,
    timeout: float = 18.0,
) -> Dict[str, Any]:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    merged = dict(_HEADERS)
    if headers:
        merged.update(headers)
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers=merged, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            return {}
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"音乐接口请求失败：{last_error}")


def _song_from_kugou_search(item: Dict[str, Any]) -> Optional[Song]:
    trans = item.get("trans_param") or {}
    hash_value = (
        item.get("hash_320")
        or item.get("hash_high")
        or item.get("hash_flac")
        or item.get("hash")
        or ""
    )
    if not hash_value:
        return None
    cover = (
        trans.get("union_cover")
        or item.get("sizable_cover")
        or item.get("album_sizable_cover")
        or ""
    )
    if cover:
        cover = cover.replace("{size}", "480")
    duration = item.get("duration") or item.get("timelength") or 0
    try:
        seconds = int(duration)
    except (TypeError, ValueError):
        seconds = 0
    if seconds > 10000:
        seconds = seconds // 1000
    return Song(
        title=item.get("songname") or item.get("filename") or "未知歌曲",
        artist=item.get("singername") or item.get("author_name") or "未知歌手",
        album=item.get("album_name") or "",
        duration=float(seconds),
        cover_url=cover,
        kugou_hash=str(hash_value),
        source="来源于网络",
    )


def _songs_from_netease_tracks(tracks: List[Dict[str, Any]]) -> List[Song]:
    songs: List[Song] = []
    seen: set[str] = set()
    for item in tracks:
        title = item.get("name") or ""
        if not title:
            continue
        artist_names = [a.get("name") or "" for a in (item.get("artists") or [])]
        artist = "、".join(name for name in artist_names if name)
        album = (item.get("album") or {}).get("name") or ""
        cover = _https((item.get("album") or {}).get("picUrl") or "")
        duration_ms = int(item.get("duration") or 0)
        song = Song(
            title=title,
            artist=artist or "未知歌手",
            album=album,
            duration=duration_ms / 1000.0,
            cover_url=cover,
            track_id=str(item.get("id") or ""),
            source="来源于网络",
        )
        if song.key not in seen:
            seen.add(song.key)
            songs.append(song)
    return songs


def _match_score(
    netease_title: str,
    netease_artist: str,
    netease_duration: float,
    kugou_song: Song,
) -> int:
    nt = _normalize(netease_title)
    kt = _normalize(kugou_song.title)
    score = 0
    if nt and nt == kt:
        score += 50
    elif nt and (nt in kt or kt in nt):
        score += 35

    n_tokens = {_normalize(x) for x in _SEPARATORS.split(netease_artist or "") if _normalize(x)}
    k_tokens = {_normalize(x) for x in _SEPARATORS.split(kugou_song.artist or "") if _normalize(x)}
    if n_tokens and k_tokens:
        if n_tokens & k_tokens:
            score += 30
        elif any(a in b or b in a for a in n_tokens for b in k_tokens):
            score += 15

    diff = abs(float(netease_duration or 0) - float(kugou_song.duration or 0))
    if diff <= 5:
        score += 20
    elif diff <= 12:
        score += 12
    elif diff <= 30:
        score += 5
    return score


def _mobile_search(keyword: str, pagesize: int = 10) -> List[Dict[str, Any]]:
    data = _http_json(
        KUGOU_MOBILE_SEARCH_URL,
        {"keyword": keyword, "page": 1, "pagesize": pagesize},
        headers={"Referer": "http://www.kugou.com/", "User-Agent": _HEADERS["User-Agent"]},
        retries=1,
        timeout=5,
    )
    if data.get("status") != 1:
        return []
    return (data.get("data") or {}).get("info") or []


def _best_kugou_candidate(
    candidates: List[Dict[str, Any]],
    title: str,
    artist: str,
    duration: float,
) -> Tuple[Optional[Song], int]:
    best: Optional[Song] = None
    best_score = 0
    for item in candidates:
        song = _song_from_kugou_search(item)
        if song is None or not song.kugou_hash:
            continue
        score = _match_score(title, artist, duration, song)
        if score > best_score:
            best_score = score
            best = song
    return best, best_score


def _kugou_search_key(
    title: str, artist: str = "", duration: float = 0.0
) -> Tuple[Any, ...]:
    first_artist = _SEPARATORS.split(artist or "")[0] if artist else ""
    duration_bucket = int(float(duration or 0) // 5.0) * 5
    return (
        "kugou_search",
        _normalize(title),
        _normalize(first_artist),
        duration_bucket,
    )


def search_kugou_song(
    title: str, artist: str = "", duration: float = 0.0
) -> Optional[Song]:
    cache_key = _kugou_search_key(title, artist, duration)
    found, cached = _cache_get(cache_key)
    if found:
        return cached

    def _search_one(query: str) -> List[Dict[str, Any]]:
        with _SEARCH_SEMAPHORE:
            try:
                return _mobile_search(query, 20)
            except Exception:
                return []

    with _SEARCH_INFLIGHT_LOCK:
        entry = _SEARCH_INFLIGHT.get(cache_key)
        if entry is not None:
            event, _result = entry
            leader = False
        else:
            event = threading.Event()
            _SEARCH_INFLIGHT[cache_key] = (event, None)
            leader = True

    if not leader:
        event.wait(timeout=30.0)
        _found, _cached = _cache_get(cache_key)
        return _cached

    try:
        first_artist = _SEPARATORS.split(artist or "")[0] if artist else ""
        candidates = _search_one(title)
        best, best_score = _best_kugou_candidate(
            candidates, title, artist, duration
        )
        if best is not None and best_score >= 60:
            _cache_set(cache_key, best, 1800)
            return best
        if first_artist:
            extra = _search_one(f"{title} {first_artist}")
            if extra:
                candidates.extend(extra)
                best, best_score = _best_kugou_candidate(
                    candidates, title, artist, duration
                )
                if best is not None and best_score >= 60:
                    _cache_set(cache_key, best, 1800)
                    return best
        if best is not None:
            _cache_set(cache_key, None, 300)
        return None
    finally:
        with _SEARCH_INFLIGHT_LOCK:
            _SEARCH_INFLIGHT.pop(cache_key, None)
            event.set()


def search_netease_song(
    title: str, artist: str = "", duration: float = 0.0
) -> Optional[Dict[str, Any]]:
    first_artist = _SEPARATORS.split(artist or "")[0] if artist else ""
    cache_key = (
        "netease_search",
        _normalize(title),
        _normalize(first_artist),
        round(float(duration or 0), 1),
    )
    found, cached = _cache_get(cache_key)
    if found:
        return cached
    queries = [title]
    if first_artist:
        queries.append(f"{title} {first_artist}")

    best: Optional[Dict[str, Any]] = None
    best_score = 0
    for query in queries[:2]:
        try:
            data = _http_json(
                NETEASE_SEARCH_URL,
                {"s": query, "type": 1, "limit": 10, "offset": 0},
                retries=2,
                timeout=15,
            )
        except Exception:
            continue
        songs = (data.get("result") or {}).get("songs") or []
        for item in songs:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or ""
            if not name:
                continue
            artist_names = [a.get("name") or "" for a in (item.get("artists") or [])]
            artist_name = "、".join(x for x in artist_names if x)
            album = (item.get("album") or {}).get("name") or ""
            duration_ms = int(item.get("duration") or 0)
            probe = Song(
                title=name,
                artist=artist_name or "未知歌手",
                album=album,
                duration=duration_ms / 1000.0,
            )
            score = _match_score(title, artist, duration, probe)
            if score > best_score:
                best_score = score
                best = item
        if best is not None and (
            best_score >= 40
            or _normalize(best.get("name") or "") == _normalize(title)
        ):
            _cache_set(cache_key, best, 1800)
            return best
    if best is not None and best_score >= 40:
        _cache_set(cache_key, best, 1800)
        return best
    if best is not None and _normalize(best.get("name") or "") == _normalize(title):
        _cache_set(cache_key, best, 1800)
        return best
    if best is not None:
        _cache_set(cache_key, None, 300)
    return None


def _append_comments(
    data: Dict[str, Any],
    comments: List[Dict[str, Any]],
    seen: set[str],
    desired: int,
) -> bool:
    items = (data.get("hotComments") or []) + (data.get("comments") or [])
    for item in items:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        if not content:
            continue
        key = content[:120]
        if key in seen:
            continue
        seen.add(key)
        user = item.get("user") or {}
        comments.append(
            {
                "nickname": user.get("nickname") or "匿名用户",
                "content": content,
                "liked": int(item.get("likedCount") or 0),
                "time": int(item.get("time") or 0),
            }
        )
        if len(comments) >= desired:
            return True
    return len(comments) >= desired


def fetch_song_comments(song: Song, limit: int = 200) -> List[Dict[str, Any]]:
    comments, _total, _next, _has_more = fetch_song_comments_page(
        song, offset=0, limit=limit, include_hot=True
    )
    return comments


def fetch_song_comments_page(
    song: Song,
    offset: int = 0,
    limit: int = 60,
    include_hot: bool = False,
    seen: Optional[set[str]] = None,
) -> Tuple[List[Dict[str, Any]], int, int, bool]:
    """Fetch one page of comments.

    Returns ``(comments, total, next_offset, has_more)``. ``seen`` lets callers
    pass already loaded content keys so repeated/overlapping API pages are
    deduplicated.
    """
    track_id = str(song.track_id or "")
    if not track_id:
        track = search_netease_song(song.title, song.artist, song.duration)
        track_id = str((track or {}).get("id") or "")
    if not track_id:
        return [], 0, False
    page_size = max(1, min(int(limit or 60), 100))
    offset_value = max(0, int(offset or 0))
    cache_key = (
        "comments_page",
        track_id,
        offset_value,
        page_size,
        bool(include_hot),
    )
    found, data = _cache_get(cache_key)
    if not found:
        data = _http_json(
            NETEASE_COMMENT_URL.format(track_id=track_id),
            {"limit": page_size, "offset": offset_value},
            retries=2,
            timeout=15,
        )
        _cache_set(cache_key, data, 900)
    total = max(0, int(data.get("total") or 0))
    seen_keys: set[str] = set(seen or ())
    comments: List[Dict[str, Any]] = []
    if include_hot:
        hot_count = len(data.get("hotComments") or [])
        _append_comments(data, comments, seen_keys, page_size + hot_count + 1)
    else:
        _append_comments(data, comments, seen_keys, page_size)
    page_count = len(data.get("comments") or [])
    next_offset = max(0, int(offset or 0)) + max(1, page_count)
    has_more = next_offset < total and (bool(comments) or page_count > 0)
    return comments, total, next_offset, has_more


def fetch_song_like_count(song: Song) -> int:
    track_id = str(song.track_id or "")
    if not track_id:
        track = search_netease_song(song.title, song.artist, song.duration)
        track_id = str((track or {}).get("id") or "")
    if not track_id:
        return 0
    cache_key = ("like_count", track_id)
    found, cached = _cache_get(cache_key)
    if found:
        return int(cached or 0)
    try:
        data = _http_json(
            "https://music.163.com/api/song/detail",
            {"ids": f"[{track_id}]"},
            retries=2,
            timeout=15,
        )
        songs = data.get("songs") or []
        if songs and isinstance(songs[0], dict):
            count = int(songs[0].get("starredNum") or 0)
            _cache_set(cache_key, count, 600)
            return count
    except Exception:
        return 0
    return 0


def fetch_rank_list() -> List[Dict[str, Any]]:
    cache_key = ("rank_list",)
    found, cached = _cache_get(cache_key)
    if found:
        return cached
    data = _http_json(NETEASE_RANK_LIST_URL, retries=2, timeout=20)
    items = data.get("list") or []
    ranks: List[Dict[str, Any]] = []
    fallback_ids: List[str] = []
    for item in items:
        rank_id = str(item.get("id") or "")
        top_songs: List[Dict[str, Any]] = []
        for track in (item.get("tracks") or [])[:5]:
            if not isinstance(track, dict):
                continue
            title = (
                track.get("name")
                or track.get("first")
                or track.get("songname")
                or ""
            )
            artists = track.get("artists") or track.get("ar") or []
            artist_names = [
                a.get("name") or ""
                for a in artists
                if isinstance(a, dict)
            ]
            artist = (
                "/".join(artist_names)
                or track.get("second")
                or track.get("singername")
                or ""
            )
            if title and artist:
                top_songs.append(
                    {"title": title, "artist": artist.replace("/", "、")}
                )
        if len(top_songs) < 5:
            fallback_ids.append(rank_id)
        ranks.append(
            {
                "rankid": rank_id,
                "rankname": item.get("name") or "未知榜单",
                "cover": _https(item.get("coverImgUrl") or ""),
                "update_frequency": item.get("updateFrequency") or "",
                "update_time": int(item.get("updateTime") or 0),
                "track_count": int(item.get("trackCount") or 0),
                "description": item.get("description") or "",
                "play_count": int(item.get("playCount") or 0),
                "subscribed_count": int(item.get("subscribedCount") or 0),
                "comment_count": int(item.get("commentCount") or 0),
                "top_songs": top_songs,
            }
        )

    top_songs_by_rank = _fetch_rank_top_songs(fallback_ids[:12], limit=5)
    for rank in ranks:
        rank_id = str(rank.get("rankid") or "")
        fallback = top_songs_by_rank.get(rank_id)
        if fallback:
            rank["top_songs"] = fallback
        elif not rank["top_songs"]:
            rank["top_songs"] = []
    # The home page grid only needs the first twelve official charts; the
    # full list stays available on the chart detail page.
    ranks = ranks[:12]
    _cache_set(cache_key, ranks, 900)
    return ranks


def _fetch_rank_top_songs(
    rank_ids: List[str], limit: int = 5, workers: int = 12
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch the first few tracks of each official rank in parallel."""
    cache_key = ("rank_top", tuple(rank_ids), int(limit))
    found, cached = _cache_get(cache_key)
    if found:
        return cached
    results: Dict[str, List[Dict[str, Any]]] = {}

    def track_summary(track: Dict[str, Any]) -> Optional[Dict[str, str]]:
        title = (
            track.get("name")
            or track.get("first")
            or track.get("songname")
            or ""
        )
        artists = track.get("artists") or track.get("ar") or []
        artist_names = [
            a.get("name") or ""
            for a in artists
            if isinstance(a, dict)
        ]
        artist = (
            "/".join(artist_names)
            or track.get("second")
            or track.get("singername")
            or ""
        )
        if not title and not artist:
            return None
        return {"title": title, "artist": artist.replace("/", "、")}

    def fetch_one(rank_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        try:
            data = _http_json(
                NETEASE_RANK_SONGS_URL,
                {"id": rank_id, "limit": max(1, limit)},
                retries=1,
                timeout=15,
            )
            result = data.get("result") or {}
            tracks = result.get("tracks") or []
            top = []
            for track in tracks[:limit]:
                if not isinstance(track, dict):
                    continue
                summary = track_summary(track)
                if summary is not None:
                    top.append(summary)
            return rank_id, top
        except Exception:
            return rank_id, []

    futures = [_RANK_EXECUTOR.submit(fetch_one, rank_id) for rank_id in rank_ids]
    for future in as_completed(futures):
        rank_id, top = future.result()
        results[rank_id] = top
    _cache_set(cache_key, results, 900)
    return results


def fetch_rank_songs(rank_id: str) -> List[Song]:
    cache_key = ("rank_songs", str(rank_id))
    found, cached = _cache_get(cache_key)
    if found:
        return list(cached)
    songs, _meta = fetch_rank_detail(rank_id)
    _cache_set(cache_key, songs, 1200)
    return songs


def fetch_rank_detail(rank_id: str) -> Tuple[List[Song], Dict[str, Any]]:
    cache_key = ("rank_detail", str(rank_id))
    found, cached = _cache_get(cache_key)
    if found:
        return cached
    data = _http_json(
        NETEASE_RANK_SONGS_URL,
        {"id": str(rank_id), "limit": 1000},
        retries=2,
        timeout=25,
    )
    result = data.get("result") or {}
    songs = _songs_from_netease_tracks(result.get("tracks") or [])
    meta = {
        "rankid": str(result.get("id") or rank_id),
        "rankname": result.get("name") or "未知榜单",
        "cover": _https(
            result.get("coverImgUrl")
            or result.get("coverImageUrl")
            or result.get("backgroundCoverUrl")
            or ""
        ),
        "description": result.get("description") or "",
        "update_time": int(result.get("updateTime") or 0),
        "track_count": int(result.get("trackCount") or len(songs)),
        "play_count": int(result.get("playCount") or 0),
        "subscribed_count": int(result.get("subscribedCount") or 0),
        "comment_count": int(result.get("commentCount") or 0),
    }
    result = (songs, meta)
    _cache_set(cache_key, result, 1200)
    return result


def match_rank_songs(
    songs: List[Song],
    progress: Optional[Callable[[str], None]] = None,
    max_workers: int = 16,
) -> Tuple[List[Song], int, List[str]]:
    total = len(songs)
    done = 0
    failures: List[str] = []
    matched_count = 0

    def work(index: int, song: Song) -> Tuple[int, Optional[Song]]:
        if song.kugou_hash or song.url:
            return index, song
        try:
            return index, search_kugou_song(song.title, song.artist, song.duration)
        except Exception as exc:
            return index, None

    last_progress = 0.0
    futures = [
        _RANK_EXECUTOR.submit(work, index, song)
        for index, song in enumerate(songs)
    ]
    for future in as_completed(futures):
        index, matched = future.result()
        done += 1
        if matched is not None and matched.kugou_hash:
            song = songs[index]
            song.kugou_hash = matched.kugou_hash
            if matched.duration:
                song.duration = matched.duration
            song.source = "来源于网络"
            matched_count += 1
        else:
            failures.append(songs[index].title)
        if progress is not None:
            now = time.monotonic()
            if done == total or done % 50 == 0 or now - last_progress >= 1.0:
                progress(
                    f"正在匹配网络音源… {done}/{total} · 已匹配 {matched_count}"
                )
                last_progress = now

    matched = total - len(failures)
    return songs, matched, failures
