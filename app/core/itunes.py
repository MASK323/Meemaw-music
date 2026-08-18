from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Dict, List

from .models import AlbumCard, BannerItem, Song

AUDIUS_BASE = "https://discoveryprovider.audius.co"
APP_NAME = "MeemawMusic"

REGION_CODES = {
    "全球": "global",
}

CHART_TYPES = {
    "热歌榜": "week",
    "新歌榜": "month",
    "最新发布": "latest",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MeemawMusic/1.0"
}


def _get_json(url: str, timeout: float = 20.0) -> dict:
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _cover_url(item: dict) -> str:
    artwork = item.get("artwork") or {}
    return artwork.get("480x480") or artwork.get("150x150") or ""


def _split_artist_title(title: str, fallback_artist: str) -> tuple[str, str]:
    text = title.strip()
    parts = [part.strip() for part in text.split(" - ") if part.strip()]
    if len(parts) >= 2:
        return " - ".join(parts[1:]), parts[0]
    return text, fallback_artist or "未知歌手"


def _song_from_item(item: Dict) -> Song | None:
    if not item:
        return None
    if item.get("is_delete"):
        return None
    if item.get("is_available") is False or item.get("is_streamable") is False:
        return None

    user = item.get("user") or {}
    fallback_artist = user.get("name") or user.get("handle") or "未知歌手"
    title, artist = _split_artist_title(item.get("title") or "未知歌曲", fallback_artist)
    album = (item.get("album_backlink") or {}).get("playlist_name") or ""
    try:
        duration = max(0, int(item.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0

    stream = item.get("stream") or {}
    stream_url = stream.get("url") or ""
    track_id = str(item.get("id") or item.get("track_id") or "")
    if stream_url:
        url = stream_url
    elif track_id:
        safe_id = urllib.parse.quote(track_id, safe="")
        url = f"{AUDIUS_BASE}/v1/tracks/{safe_id}/stream?app_name={APP_NAME}"
    else:
        url = ""
    if not url:
        return None

    fallback_url = ""
    if track_id:
        safe_id = urllib.parse.quote(track_id, safe="")
        endpoint = f"{AUDIUS_BASE}/v1/tracks/{safe_id}/stream?app_name={APP_NAME}"
        if endpoint != url:
            fallback_url = endpoint

    return Song(
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        url=url,
        cover_url=_cover_url(item),
        track_id=track_id,
        source="在线完整曲目",
        fallback_url=fallback_url,
    )


def _filter_songs(items: List) -> List[Song]:
    songs = []
    for item in items:
        song = _song_from_item(item)
        if song is not None:
            songs.append(song)
    return songs


def _fetch_tracks(path: str, params: Dict) -> List[Song]:
    params["app_name"] = APP_NAME
    params["limit"] = int(params.get("limit", 30))
    query = urllib.parse.urlencode(params)
    data = _get_json(f"{AUDIUS_BASE}{path}?{query}")
    return _filter_songs(data.get("data") or [])


def fetch_chart(
    region_code: str = "global",
    chart_key: str = "week",
    limit: int = 25,
) -> List[Song]:
    if chart_key == "latest":
        return fetch_new_songs(region_code, limit)
    time_value = chart_key if chart_key in ("week", "month", "year") else "week"
    return _fetch_tracks("/v1/tracks/trending", {"time": time_value, "limit": limit})


def fetch_new_songs(region_code: str = "global", limit: int = 12) -> List[Song]:
    return _fetch_tracks("/v1/tracks/latest", {"limit": limit})


def fetch_playlist_tracks(playlist_id: str, limit: int = 30) -> List[Song]:
    if not playlist_id:
        return []
    safe_id = urllib.parse.quote(str(playlist_id), safe="")
    return _fetch_tracks(f"/v1/playlists/{safe_id}/tracks", {"limit": limit})


def fetch_albums(region_code: str = "global", limit: int = 12) -> List[AlbumCard]:
    data = _get_json(
        f"{AUDIUS_BASE}/v1/playlists/trending?"
        f"app_name={APP_NAME}&limit={int(limit)}"
    )
    cards = []
    for item in data.get("data") or []:
        user = item.get("user") or {}
        cards.append(
            AlbumCard(
                title=item.get("playlist_name") or item.get("title") or "未知歌单",
                artist=user.get("name") or user.get("handle") or "",
                cover_url=_cover_url(item),
                url=item.get("permalink") or "",
                album_id=str(item.get("id") or ""),
            )
        )
    return cards


def fetch_banners(region_code: str = "global", limit: int = 3) -> List[BannerItem]:
    songs = fetch_chart(region_code, "week", max(limit, 6))
    banners = []
    for index, song in enumerate(songs[:limit]):
        banners.append(
            BannerItem(
                title=song.title,
                subtitle=f"{song.artist} · 全球热播",
                cover_url=song.cover_url,
                song=song,
            )
        )
    return banners


def search_songs(term: str, limit: int = 30) -> List[Song]:
    if not term.strip():
        return []
    return _fetch_tracks("/v1/tracks/search", {"query": term, "limit": limit})
