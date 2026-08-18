"""External playlist importers for QQ Music, NetEase and Apple Music.

The importer only converts public playlist metadata to Meemaw's existing
``Song`` model.  Playback still goes through the configured audio sources,
so importing a playlist never removes covers, lyrics, comments or queue
behaviour.  URL parsers are intentionally conservative and also accept a
plain ``title - artist`` text list for private playlists.
"""
from __future__ import annotations

import base64
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.core.models import Song
from app.core.source_manager import normalize_text


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


def _json_request(url: str, timeout: float = 12.0, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers={**_HEADERS, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_html": text}


def _post_form(url: str, form: dict[str, str], timeout: float = 15.0, headers: dict[str, str] | None = None) -> Any:
    encoded = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={**_HEADERS, "Content-Type": "application/x-www-form-urlencoded", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_html": text}


def _text_request(url: str, timeout: float = 12.0, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, headers={**_HEADERS, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _first(value: Any, *keys: str, default: Any = "") -> Any:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
    return default


def _duration(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    # QQ and Apple commonly use milliseconds; NetEase uses milliseconds too.
    return number / 1000.0 if number > 1000 else number


def _split_artists(value: Any) -> str:
    if isinstance(value, list):
        names = [_first(item, "name", "artistName", default="") for item in value]
        return " / ".join(str(name).strip() for name in names if str(name).strip())
    if isinstance(value, dict):
        return str(_first(value, "name", "artistName", "artist", default="")).strip()
    return str(value or "").strip()


def _track(title: Any, artist: Any, album: Any = "", duration: Any = 0, track_id: Any = "", cover: Any = "", provider: str = "") -> dict[str, Any] | None:
    title_text = html.unescape(str(title or "")).strip()
    artist_text = _split_artists(artist)
    if not title_text:
        return None
    album_text = _first(album, "name", "title", "albumName", default="") if isinstance(album, dict) else album
    return {
        "title": title_text,
        "artist": artist_text or "未知歌手",
        "album": str(album_text or "").strip(),
        "duration": _duration(duration),
        "external_id": str(track_id or ""),
        "cover_url": str(cover or ""),
        "provider": provider,
    }


def detect_provider(value: str, forced: str = "auto") -> str:
    if forced and forced != "auto":
        return forced
    text = str(value or "").lower()
    if "music.163.com" in text or "163cn.tv" in text:
        return "netease"
    if "qq.com" in text or "qqmusic" in text or "y.qq.com" in text:
        return "qqmusic"
    if "music.apple.com" in text or "itunes.apple.com" in text:
        return "apple"
    return "text"


def _extract_id(value: str, provider: str) -> str:
    text = str(value or "").strip()
    if text.isdigit():
        return text
    if provider == "netease":
        match = re.search(r"(?:playlist\?id=|playlist/|id=)(\d+)", text)
        if match:
            return match.group(1)
    if provider == "qqmusic":
        match = re.search(r"(?:playlist/|disstid=|tid=|id=)([A-Za-z0-9_-]+)", text)
        if match:
            return match.group(1)
    if provider == "apple":
        match = re.search(r"/(pl\.[A-Za-z0-9._-]+)", text)
        if match:
            return match.group(1)
    return ""


def _netease(value: str) -> dict[str, Any]:
    playlist_id = _extract_id(value, "netease")
    if not playlist_id:
        raise ValueError("未识别网易云歌单 ID")
    # v6 returns the playlist metadata and as many complete tracks as the
    # service allows. This is the same endpoint used by EchoMusic and is more
    # reliable for large public playlists than the legacy detail endpoint.
    url = "https://music.163.com/api/v6/playlist/detail?" + urllib.parse.urlencode({"id": playlist_id, "n": 100000})
    payload = _json_request(url, headers={"Referer": "https://music.163.com/"})
    playlist = (payload or {}).get("playlist") if isinstance(payload, dict) else None
    if not isinstance(playlist, dict):
        raise ValueError("网易云歌单为空或需要登录")
    tracks: list[dict[str, Any]] = []
    raw_tracks = playlist.get("tracks") or []
    # The detail endpoint returns only partial metadata for large playlists.
    # Fetch the full public track list when only trackIds are present.
    if not raw_tracks and playlist.get("trackIds"):
        # The v3 endpoint accepts up to 500 ids per request and fills in the
        # partial trackIds returned for large playlists.
        ids = [str(item.get("id") if isinstance(item, dict) else item) for item in playlist.get("trackIds") or []]
        ids = [item for item in ids if item and item != "None"]
        try:
            full: list[dict[str, Any]] = []
            for start in range(0, len(ids), 500):
                body = json.dumps([{"id": item} for item in ids[start : start + 500]], ensure_ascii=False, separators=(",", ":"))
                detail = _post_form(
                    "https://music.163.com/api/v3/song/detail",
                    {"c": body},
                    headers={"Referer": "https://music.163.com/"},
                )
                if isinstance(detail, dict):
                    full.extend(detail.get("songs") or [])
            raw_tracks = full
        except (OSError, ValueError, urllib.error.URLError):
            raw_tracks = playlist.get("trackIds") or []
    for item in raw_tracks:
        if not isinstance(item, dict):
            continue
        song = _track(
            _first(item, "name", "title"),
            _first(item, "ar", "artists", "artist"),
            _first(item, "al", "album"),
            _first(item, "dt", "duration", "duration_ms"),
            _first(item, "id"),
            _first(_first(item, "al", "album", default={}) or {}, "picUrl", "pic_url"),
            "netease",
        )
        if song:
            tracks.append(song)
    return {
        "provider": "netease",
        "external_id": playlist_id,
        "name": _first(playlist, "name", default="网易云歌单"),
        "description": _first(playlist, "description", default=""),
        "cover_url": str(playlist.get("coverImgUrl") or ""),
        "creator": _first(playlist.get("creator") or {}, "nickname", default=""),
        "tracks": tracks,
    }


def _qqmusic(value: str) -> dict[str, Any]:
    playlist_id = _extract_id(value, "qqmusic")
    if not playlist_id:
        raise ValueError("未识别 QQ 音乐歌单 ID")
    url = "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg?" + urllib.parse.urlencode({
        "format": "json", "inCharset": "utf8", "outCharset": "utf-8", "notice": 0,
        "platform": "yqq", "needNewCode": 0, "disstid": playlist_id,
    })
    payload = _json_request(url, headers={"Referer": "https://y.qq.com/"})
    cd_list = payload.get("cdlist") if isinstance(payload, dict) else None
    playlist = cd_list[0] if isinstance(cd_list, list) and cd_list else None
    if not isinstance(playlist, dict):
        raise ValueError("QQ 音乐歌单为空、隐私或需要登录")
    tracks: list[dict[str, Any]] = []
    for item in playlist.get("songlist") or []:
        if not isinstance(item, dict):
            continue
        album = item.get("album") or {}
        song = _track(
            _first(item, "songname", "name"),
            _first(item, "singer", "artists", "artist"),
            _first(album, "name", "title"),
            _first(item, "interval", "duration"),
            _first(item, "songmid", "songid", "id"),
            "https://y.gtimg.cn/music/photo_new/T002R300x300M000%s.jpg" % _first(album, "mid", default="") if _first(album, "mid") else "",
            "qqmusic",
        )
        if song:
            tracks.append(song)
    return {
        "provider": "qqmusic",
        "external_id": playlist_id,
        "name": _first(playlist, "dissname", "name", default="QQ 音乐歌单"),
        "description": _first(playlist, "desc", "description", default=""),
        "cover_url": _first(playlist, "logo", "picurl", default=""),
        "creator": _first(playlist, "nickname", "creator", default=""),
        "tracks": tracks,
    }


_APPLE_TOKEN: tuple[str, float] | None = None


def _decode_json_string(value: str) -> str:
    try:
        return json.loads('"' + value + '"')
    except (TypeError, ValueError, json.JSONDecodeError):
        return value.replace('\\"', '"').replace('\\n', ' ')


def _apple_playlist_info(value: str) -> tuple[str, str]:
    text = str(value or '').strip()
    playlist_id = _extract_id(text, 'apple')
    if not playlist_id:
        raise ValueError('未识别 Apple Music 歌单 ID')
    storefront_match = re.search(r'music\.apple\.com/([a-z]{2})(?:-[A-Z]{2})?/', text, re.I)
    return playlist_id, (storefront_match.group(1).lower() if storefront_match else 'us')


def _apple_developer_token() -> str:
    global _APPLE_TOKEN
    now = time.time()
    if _APPLE_TOKEN and now < _APPLE_TOKEN[1]:
        return _APPLE_TOKEN[0]
    homepage = _text_request('https://music.apple.com', headers={'User-Agent': _HEADERS['User-Agent']})
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', homepage, re.I)
    bundle_urls = []
    for src in scripts:
        bundle_urls.append(urllib.parse.urljoin('https://music.apple.com', html.unescape(src)))
    # Apple occasionally renames the entry bundle; try every script instead of
    # relying on one generated filename.
    for bundle_url in bundle_urls[:12]:
        try:
            bundle = _text_request(bundle_url, headers={'User-Agent': _HEADERS['User-Agent']})
        except (OSError, urllib.error.URLError):
            continue
        for token in re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', bundle):
            try:
                payload = token.split('.')[1]
                payload += '=' * (-len(payload) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload).decode('utf-8'))
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
                continue
            if claims.get('iss') == 'AMPWebPlay' and claims.get('exp'):
                _APPLE_TOKEN = (token, max(now + 300, float(claims['exp']) - 3600))
                return token
    raise ValueError('无法从 Apple Music 页面获取公开开发者令牌')


def _apple_from_api(value: str) -> dict[str, Any]:
    playlist_id, storefront = _apple_playlist_info(value)
    token = _apple_developer_token()
    headers = {
        'Authorization': 'Bearer ' + token,
        'Origin': 'https://music.apple.com',
        'User-Agent': _HEADERS['User-Agent'],
    }
    url = f'https://amp-api.music.apple.com/v1/catalog/{storefront}/playlists/{playlist_id}?include=tracks&l=zh-Hans-CN'
    payload = _json_request(url, headers=headers)
    playlist_items = payload.get('data') if isinstance(payload, dict) else None
    playlist = playlist_items[0] if isinstance(playlist_items, list) and playlist_items else None
    if not isinstance(playlist, dict):
        errors = payload.get('errors') if isinstance(payload, dict) else None
        detail = errors[0].get('detail') if isinstance(errors, list) and errors and isinstance(errors[0], dict) else ''
        raise ValueError(detail or 'Apple Music 歌单为空、受地区限制或需要登录')
    relationships = playlist.get('relationships') or {}
    track_page = relationships.get('tracks') or {}
    raw_tracks = list(track_page.get('data') or [])
    next_url = track_page.get('next')
    for _ in range(10):
        if not next_url:
            break
        page_url = urllib.parse.urljoin('https://amp-api.music.apple.com', str(next_url))
        page = _json_request(page_url, headers=headers)
        if not isinstance(page, dict):
            break
        raw_tracks.extend(page.get('data') or [])
        next_url = page.get('next')
    attrs = playlist.get('attributes') or {}
    artwork = attrs.get('artwork') or {}
    cover = str(artwork.get('url') or '').replace('{w}', '600').replace('{h}', '600')
    tracks: list[dict[str, Any]] = []
    for item in raw_tracks:
        if not isinstance(item, dict):
            continue
        attrs = item.get('attributes') or {}
        song = _track(
            attrs.get('name'), attrs.get('artistName'), attrs.get('albumName'),
            attrs.get('durationInMillis'), item.get('id'), cover, 'apple',
        )
        if song:
            tracks.append(song)
    if not tracks:
        raise ValueError('该 Apple Music 歌单没有公开歌曲')
    return {
        'provider': 'apple',
        'external_id': playlist_id,
        'name': _first(playlist.get('attributes') or {}, 'name', default='Apple Music 歌单'),
        'description': _first(playlist.get('attributes') or {}, 'description', default=''),
        'cover_url': cover,
        'creator': _first(playlist.get('attributes') or {}, 'curatorName', default=''),
        'tracks': tracks,
    }


def _apple_from_page(value: str) -> dict[str, Any]:
    playlist_id = _extract_id(value, 'apple')
    page_url = value if str(value).startswith('http') else 'https://music.apple.com/us/playlist/' + playlist_id
    page = _text_request(page_url)
    text = html.unescape(page)
    tracks: list[dict[str, Any]] = []
    pattern = re.compile(
        r'"(?:trackName|name)"\s*:\s*"(?P<title>(?:\\.|[^"\\])+)".*?'
        r'"(?:artistName|byArtist)"\s*:\s*"(?P<artist>(?:\\.|[^"\\])+)', re.S,
    )
    seen: set[tuple[str, str]] = set()
    for match in pattern.finditer(text):
        title = _decode_json_string(match.group('title')).strip()
        artist = _decode_json_string(match.group('artist')).strip()
        key = (normalize_text(title), normalize_text(artist))
        if title and key not in seen:
            seen.add(key)
            song = _track(title, artist, provider='apple')
            if song:
                tracks.append(song)
    if not tracks:
        for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.S | re.I):
            try:
                data = json.loads(html.unescape(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            entries = data if isinstance(data, list) else [data]
            for item in entries:
                if not isinstance(item, dict):
                    continue
                song = _track(_first(item, 'name', 'trackName'), _first(item, 'byArtist', 'artist'), provider='apple')
                if song:
                    tracks.append(song)
    if not tracks:
        raise ValueError('Apple Music 页面未公开歌曲列表，请粘贴文本歌单')
    return {'provider': 'apple', 'external_id': playlist_id, 'name': 'Apple Music 歌单', 'tracks': tracks}


def _apple(value: str) -> dict[str, Any]:
    try:
        # Public catalog API gives complete metadata and pagination. If Apple
        # changes the token bundle, keep the older public-page parser as a
        # graceful fallback for pages that still expose embedded track data.
        return _apple_from_api(value)
    except (OSError, ValueError, urllib.error.URLError):
        return _apple_from_page(value)

def _text_playlist(value: str) -> dict[str, Any]:
    tracks: list[dict[str, Any]] = []
    for line in str(value or "").splitlines():
        line = line.strip().lstrip("-•* ")
        if not line:
            continue
        parts = re.split(r"\s+-\s+|\s+—\s+|\t+", line, maxsplit=1)
        title, artist = (parts + ["未知歌手"])[:2]
        song = _track(title, artist, provider="text")
        if song:
            tracks.append(song)
    if not tracks:
        raise ValueError("请输入歌单链接、ID，或每行一首‘歌名 - 歌手’")
    return {"provider": "text", "name": "文本歌单", "tracks": tracks}


def resolve_playlist(value: str, provider: str = "auto") -> dict[str, Any]:
    kind = detect_provider(value, provider)
    if kind == "netease":
        return _netease(value)
    if kind == "qqmusic":
        return _qqmusic(value)
    if kind == "apple":
        return _apple(value)
    return _text_playlist(value)


def _score(external: dict[str, Any], candidate: Any) -> float:
    title_a = normalize_text(external.get("title"))
    artist_a = normalize_text(external.get("artist"))
    title_b = normalize_text(getattr(candidate, "title", ""))
    artist_b = normalize_text(getattr(candidate, "artist", ""))
    if not title_a or not title_b:
        return 0.0
    title = 1.0 if title_a == title_b else (0.8 if title_a in title_b or title_b in title_a else 0.0)
    artist = 1.0 if artist_a and (artist_a == artist_b or artist_a in artist_b or artist_b in artist_a) else 0.0
    duration_a = float(external.get("duration") or 0)
    duration_b = float(getattr(candidate, "duration", 0) or 0)
    duration = 1.0 if not duration_a or not duration_b else max(0.0, 1.0 - abs(duration_a - duration_b) / 15.0)
    return title * 0.62 + artist * 0.28 + duration * 0.10


def match_playlist_tracks(playlist: dict[str, Any], kugou_client: Any, workers: int = 4) -> list[Song]:
    """Map external tracks to Kugou-hash Songs concurrently and de-duplicate."""
    tracks = [item for item in playlist.get("tracks") or [] if isinstance(item, dict)]
    if not tracks:
        return []
    cache: dict[tuple[str, str, str], Song | None] = {}
    lock = __import__("threading").Lock()

    def match(item: dict[str, Any]) -> Song | None:
        key = (normalize_text(item.get("title")), normalize_text(item.get("artist")), str(round(float(item.get("duration") or 0))))
        with lock:
            if key in cache:
                return cache[key]
        term = " ".join(part for part in (item.get("title"), item.get("artist")) if part)
        try:
            response = kugou_client.search_songs(term, limit=6)
            # KugouClient returns (songs, error_text); tolerate lightweight
            # test clients and older builds that return the list directly.
            if isinstance(response, tuple):
                candidates = response[0] if response else []
            else:
                candidates = response
        except Exception:
            candidates = []
        candidates = candidates if isinstance(candidates, (list, tuple)) else []
        best = max(candidates, key=lambda candidate: _score(item, candidate), default=None)
        result = best if best is not None and _score(item, best) >= 0.52 else None
        with lock:
            cache[key] = result
        return result

    ordered: list[Song | None] = [None] * len(tracks)
    with ThreadPoolExecutor(max_workers=max(1, min(6, int(workers))), thread_name_prefix="mm-playlist") as pool:
        futures = {pool.submit(match, item): index for index, item in enumerate(tracks)}
        for future in as_completed(futures):
            try:
                ordered[futures[future]] = future.result()
            except Exception:
                ordered[futures[future]] = None
    result: list[Song] = []
    seen: set[str] = set()
    for song in ordered:
        if song is None or song.key in seen:
            continue
        seen.add(song.key)
        result.append(song)
    return result


def import_playlist(value: str, provider: str, kugou_client: Any) -> dict[str, Any]:
    playlist = resolve_playlist(value, provider)
    songs = match_playlist_tracks(playlist, kugou_client)
    return {"playlist": playlist, "songs": songs, "matched": len(songs), "total": len(playlist.get("tracks") or [])}


__all__ = ["detect_provider", "resolve_playlist", "match_playlist_tracks", "import_playlist"]
