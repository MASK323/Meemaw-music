from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .lyrics import parse_lyrics
from .models import AlbumCard, BannerItem, LyricLine, Song

API_PORT = 6521
API_FALLBACK_PORT = 6522

QUALITY_ORDER = ["128", "320", "flac", "high"]
_URL_CACHE_TTL = 900.0


def _local_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _api_exe_path() -> Path:
    return _local_path() / "api" / "app_win.exe"


def _cover(raw: str, size: int = 480) -> str:
    if not raw:
        return ""
    return raw.replace("{size}", str(size))


def _seconds(value: Any) -> float:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if number > 10000:
        return number / 1000.0
    return float(number)


_VIP_SOURCE_KEYS = {
    "vip_type": "vip_type",
    "product_type": "product_type",
    "vipgrade": "vip_grade",
    "vip_grade": "vip_grade",
    "vip_level": "vip_grade",
    "is_vip": "is_vip",
    "vip_flag": "is_vip",
    "vip_status": "is_vip",
    "user_vip": "is_vip",
    "vip_open": "is_vip",
    "is_member": "is_vip",
}
_VIP_EXPIRE_KEYS = {
    "vip_expire": "vip_expire",
    "vip_expire_time": "vip_expire",
    "vip_end_time": "vip_expire",
    "vip_end": "vip_expire",
    "vip_deadline": "vip_expire",
    "vip_time": "vip_expire",
    "expire_time": "vip_expire",
    "expires": "vip_expire",
    "deadline": "vip_expire",
}
_VIP_DAYS_KEYS = {
    "vip_days": "vip_days",
    "remain_days": "vip_days",
    "remaining_days": "vip_days",
    "vip_remain_days": "vip_days",
    "left_days": "vip_days",
    "surplus_days": "vip_days",
    "vip_remain": "vip_days",
}
def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "y", "on", "vip", "member", "会员")


def _normalize_vip_type(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = int(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        if text and text.lower() not in ("0", "none", "null", "普通", "普通用户"):
            return "概念版会员"
        return ""
    return "概念版会员" if number else ""


def _normalize_expire(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in ("0", "none", "null", "-"):
        return ""
    match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if match:
        try:
            year, month, day = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            pass
    try:
        number = float(text)
    except ValueError:
        return ""
    if number <= 0:
        return ""
    if number > 100000000000:
        number /= 1000.0
    if number < 1000000000:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(number))
    except (OverflowError, OSError, ValueError):
        return ""


def _extract_member_fields(payload: Any) -> Dict[str, Any]:
    """Pick VIP fields out of an API payload without trusting any one schema."""
    aliases: Dict[str, str] = {}
    aliases.update(_VIP_SOURCE_KEYS)
    aliases.update(_VIP_EXPIRE_KEYS)
    aliases.update(_VIP_DAYS_KEYS)
    found: Dict[str, Any] = {}

    def scalar(value: Any) -> bool:
        return value is not None and not isinstance(value, (dict, list))

    def walk(node: Any, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                normalized = aliases.get(str(key).lower().strip())
                if normalized and normalized not in found and scalar(value):
                    found[normalized] = value
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    walk(item, depth + 1)

    walk(payload, 0)
    info: Dict[str, Any] = {}
    vip_sources = [
        found.get(key)
        for key in ("is_vip", "vip_flag", "vip_status", "user_vip", "vip_open", "is_member")
        if found.get(key) is not None
    ]
    if "vip_type" in found or vip_sources:
        is_vip = bool(_normalize_vip_type(found.get("vip_type")))
        if not is_vip:
            is_vip = any(_bool_value(source) for source in vip_sources)
        info["is_vip"] = is_vip
        name = _normalize_vip_type(found.get("vip_type"))
        product = str(found.get("product_type") or "").lower()
        if is_vip:
            if product == "svip":
                name = "概念版会员"
            elif product:
                name = "畅听版会员"
            elif not name:
                name = "概念版会员"
        if name:
            info["vip_name"] = name
    if "vip_expire" in found:
        expire = _normalize_expire(found["vip_expire"])
        if expire:
            info["vip_expire"] = expire
    if "vip_days" in found:
        try:
            info["vip_days"] = max(0, int(float(found["vip_days"])))
        except (TypeError, ValueError):
            pass
    return info


def _vip_days_from_expire(expire: str) -> Optional[int]:
    if not expire:
        return None
    try:
        expire_date = datetime.strptime(expire, "%Y-%m-%d").date()
        return max(0, (expire_date - date.today()).days + 1)
    except (ValueError, OverflowError, OSError):
        return None


def _extract_busi_vip(payload: Any) -> Dict[str, Any]:
    """Parse /user/vip/detail's data.busi_vip, matching MoeKoe Music's schema."""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    busi = data.get("busi_vip") if isinstance(data, dict) else None
    if not isinstance(busi, list):
        return {}
    entries: List[Dict[str, Any]] = []
    for item in busi:
        if not isinstance(item, dict):
            continue
        if not _bool_value(item.get("is_vip")):
            continue
        product = str(item.get("product_type") or "").lower()
        if product != "svip":
            continue
        expire = _normalize_expire(item.get("vip_end_time"))
        name = "概念版会员"
        entry: Dict[str, Any] = {
            "product_type": product,
            "name": name,
            "is_vip": True,
            "vip_expire": expire,
            "vip_grade": item.get("vip_grade"),
        }
        days = _vip_days_from_expire(expire)
        if days is not None:
            entry["vip_days"] = days
        entries.append(entry)
        break
    if not entries:
        return {}
    entries.sort(key=lambda entry: entry["product_type"] != "svip")
    primary = entries[0]
    info: Dict[str, Any] = {
        "is_vip": True,
        "vip_list": entries,
        "vip_name": primary["name"],
        "vip_expire": primary.get("vip_expire") or "",
        "vip_grade": primary.get("vip_grade"),
    }
    days = primary.get("vip_days")
    if days is not None:
        info["vip_days"] = days
    return info


def _first_song_hash(item: Dict[str, Any]) -> str:
    for key in ("hash_320", "hash_high", "hash_flac", "hash_128", "hash"):
        value = item.get(key)
        if value:
            return str(value)
    audio = item.get("audio_info") or {}
    for key in ("hash_320", "hash_high", "hash_flac", "hash_128"):
        value = audio.get(key)
        if value:
            return str(value)
    return ""


def _song_from_rank(item: Dict[str, Any]) -> Song | None:
    audio = item.get("audio_info") or {}
    trans = item.get("trans_param") or {}
    album = item.get("album_info") or {}
    hash_value = _first_song_hash(item)
    if not hash_value:
        return None
    duration = (
        audio.get("duration_128")
        or audio.get("duration_320")
        or item.get("duration")
        or 0
    )
    cover = (
        trans.get("union_cover")
        or album.get("sizable_cover")
        or item.get("sizable_cover")
    )
    return Song(
        title=item.get("songname") or item.get("filename") or "未知歌曲",
        artist=item.get("author_name") or "未知歌手",
        album=album.get("album_name") or "",
        duration=_seconds(duration),
        cover_url=_cover(cover),
        kugou_hash=hash_value,
        source="来源于网络",
    )


def _song_from_top(item: Dict[str, Any]) -> Song | None:
    hash_value = (
        item.get("hash_320")
        or item.get("hash_high")
        or item.get("hash_flac")
        or item.get("hash")
        or ""
    )
    if not hash_value:
        return None
    duration = item.get("timelength") or item.get("duration") or 0
    cover = item.get("album_sizable_cover") or (item.get("trans_param") or {}).get(
        "union_cover"
    )
    return Song(
        title=item.get("songname") or "未知歌曲",
        artist=item.get("author_name") or "未知歌手",
        album=item.get("album_name") or "",
        duration=_seconds(duration),
        cover_url=_cover(cover),
        kugou_hash=str(hash_value),
        source="来源于网络",
    )


def _song_from_playlist(item: Dict[str, Any]) -> Song | None:
    hash_value = item.get("hash") or ""
    if not hash_value:
        return None
    duration = item.get("timelen") or item.get("time_length") or 0
    cover = item.get("cover") or item.get("sizable_cover") or ""
    return Song(
        title=item.get("name") or item.get("songname") or "未知歌曲",
        artist=item.get("author_name") or item.get("singername") or "未知歌手",
        album=item.get("album_name") or "",
        duration=_seconds(duration),
        cover_url=_cover(cover),
        kugou_hash=str(hash_value),
        source="来源于网络",
    )


def _song_from_search(item: Dict[str, Any]) -> Song | None:
    hash_value = (
        item.get("hash_320")
        or item.get("hash_high")
        or item.get("hash_flac")
        or item.get("hash")
        or ""
    )
    if not hash_value:
        return None
    duration = item.get("timelength") or item.get("duration") or 0
    cover = item.get("album_sizable_cover") or (item.get("trans_param") or {}).get(
        "union_cover"
    )
    return Song(
        title=item.get("songname") or item.get("filename") or "未知歌曲",
        artist=item.get("author_name") or item.get("singername") or "未知歌手",
        album=item.get("album_name") or "",
        duration=_seconds(duration),
        cover_url=_cover(cover),
        kugou_hash=str(hash_value),
        source="来源于网络",
    )


class KugouAPIError(RuntimeError):
    pass


def _md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


class KugouClient:
    def __init__(self, port: int = API_PORT) -> None:
        self._port = port
        self._base = f"http://127.0.0.1:{port}"
        self.quality: str = "320"
        self._proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._device: Dict[str, Any] = {}
        self._login: Dict[str, Any] = {}
        self._login_path = _local_path() / "kugou_login.json"
        self._device_path = _local_path() / "kugou_dev.json"
        self._url_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
        self._url_cache_lock = threading.Lock()
        self._last_url_save = 0.0
        self._url_cache_dirty = False
        self._url_save_writer: Optional[threading.Thread] = None
        self._url_save_dirty = False
        self._url_save_released = False
        appdata = os.environ.get("APPDATA") or str(Path.home())
        self._url_cache_path = Path(appdata) / "MeemawMusic" / "url_cache.json"
        self._load_device()
        self._load_login()
        self._load_url_cache()

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def logged_in(self) -> bool:
        with self._state_lock:
            return bool(self._login.get("token") and self._login.get("userid"))

    @property
    def nickname(self) -> str:
        with self._state_lock:
            return str(self._login.get("nickname") or "网络用户")

    def user_id(self) -> str:
        with self._state_lock:
            return str(self._login.get("userid") or "")

    @property
    def member_info(self) -> Dict[str, Any]:
        with self._state_lock:
            is_vip = _bool_value(self._login.get("is_vip"))
            vip_days = self._login.get("vip_days") or 0
            try:
                vip_days = max(0, int(float(vip_days)))
            except (TypeError, ValueError):
                vip_days = 0
            if vip_days <= 0:
                computed_days = _vip_days_from_expire(
                    str(self._login.get("vip_expire") or "")
                )
                if computed_days is not None:
                    vip_days = computed_days
            vip_list = self._login.get("vip_list") or []
            if not isinstance(vip_list, list):
                vip_list = []
            vip_list = vip_list[:1]
            return {
                "is_vip": is_vip,
                "vip_name": str(self._login.get("vip_name") or ""),
                "vip_expire": str(self._login.get("vip_expire") or ""),
                "vip_days": vip_days,
                "vip_list": vip_list,
                "last_synced": str(self._login.get("member_synced_at") or ""),
            }

    def auth_headers(self) -> Dict[str, str]:
        with self._state_lock:
            device = dict(self._device)
            login = dict(self._login)
        parts: List[str] = []
        for key, value in (
            ("token", login.get("token")),
            ("userid", login.get("userid")),
            ("dfid", device.get("dfid")),
            ("t1", login.get("t1")),
            ("KUGOU_API_MID", device.get("mid")),
            ("KUGOU_API_GUID", device.get("guid")),
            ("KUGOU_API_DEV", device.get("serverDev")),
            ("KUGOU_API_MAC", device.get("mac")),
        ):
            if value:
                parts.append(f"{key}={value}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MeemawMusic/1.0",
            "Content-Type": "application/json",
        }
        if parts:
            headers["Authorization"] = ";".join(parts)
        return headers

    def start(self) -> None:
        if self._is_reachable():
            self._ensure_device()
            return
        with self._proc_lock:
            if self._proc is not None and self._proc.poll() is None:
                self._ensure_device()
                return
            exe = _api_exe_path()
            if not exe.exists():
                raise KugouAPIError(f"未找到本地音乐 API 程序：{exe}")
            try:
                self._proc = subprocess.Popen(
                    [
                        str(exe),
                        "--platform=lite",
                        f"--port={self._port}",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as exc:
                raise KugouAPIError(f"启动本地音乐 API 失败：{exc}") from exc
            deadline = time.time() + 15
            while time.time() < deadline:
                if self._is_reachable():
                    self._ensure_device()
                    return
                if self._proc.poll() is not None:
                    break
                time.sleep(0.25)
        raise KugouAPIError("本地音乐 API 启动超时")

    def _ensure_device(self) -> None:
        try:
            self.register_device()
        except KugouAPIError:
            pass

    def stop(self) -> None:
        self._save_url_cache()
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        elif proc is None and self._is_reachable(timeout=0.5):
            self._stop_external_api()

    def _stop_external_api(self) -> None:
        """Stop a previously launched API process that this client did not start."""
        try:
            output = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                text=True,
                errors="ignore",
                timeout=5,
            )
            pid: Optional[int] = None
            suffix = f":{self._port}"
            for line in output.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    and parts[0] == "TCP"
                    and parts[1].endswith(suffix)
                    and parts[3] == "LISTENING"
                ):
                    try:
                        pid = int(parts[4])
                    except ValueError:
                        continue
                    break
            if pid is not None:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=5,
                )
        except Exception:
            pass

    def _is_reachable(self, timeout: float = 0.6) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self._port), timeout=timeout):
                return True
        except OSError:
            return False

    def _load_login(self) -> None:
        try:
            if self._login_path.exists():
                with open(self._login_path, "r", encoding="utf-8") as handle:
                    self._login = json.loads(handle.read() or "{}")
        except Exception:
            self._login = {}

    def _load_device(self) -> None:
        try:
            if self._device_path.exists():
                with open(self._device_path, "r", encoding="utf-8") as handle:
                    self._device = json.loads(handle.read() or "{}")
        except Exception:
            self._device = {}

    def _save_device(self) -> None:
        try:
            with open(self._device_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(self._device, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _save_login(self) -> None:
        try:
            with open(self._login_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(self._login, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _load_url_cache(self) -> None:
        try:
            if not self._url_cache_path.exists():
                return
            with open(self._url_cache_path, "r", encoding="utf-8") as handle:
                data = json.loads(handle.read() or "{}")
            now = time.time()
            with self._url_cache_lock:
                for key, entry in data.items():
                    parts = key.split("|", 1)
                    if len(parts) != 2:
                        continue
                    timestamp = float(entry.get("ts") or 0)
                    result = entry.get("result") or {}
                    if (
                        0 < timestamp <= now
                        and now - timestamp < _URL_CACHE_TTL
                        and result.get("url")
                    ):
                        self._url_cache[(parts[0], parts[1])] = (
                            timestamp,
                            result,
                        )
        except Exception:
            pass

    def _save_url_cache(self) -> None:
        try:
            self._url_cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self._url_cache_lock:
                data = {
                    f"{hash_value}|{quality}": {
                        "ts": timestamp,
                        "result": result,
                    }
                    for (hash_value, quality), (timestamp, result) in self._url_cache.items()
                }
            # Write the snapshot without holding the cache lock so a large
            # cache never blocks URL resolution while it is being saved.
            temp_path = self._url_cache_path.with_suffix(".json.tmp")
            try:
                with open(temp_path, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(data, ensure_ascii=False))
                os.replace(temp_path, self._url_cache_path)
            except OSError:
                # A stale process may briefly hold the cache file; fall back
                # to a direct rewrite so fresh URLs are still persisted.
                try:
                    with open(self._url_cache_path, "w", encoding="utf-8") as handle:
                        handle.write(json.dumps(data, ensure_ascii=False))
                except OSError:
                    raise
            with self._url_cache_lock:
                self._url_cache_dirty = False
        except Exception:
            pass

    def _maybe_save_url_cache(self) -> None:
        now = time.time()
        with self._url_cache_lock:
            if not self._url_cache_dirty:
                self._last_url_save = now
                return
        if now - self._last_url_save < 5.0:
            return
        self._last_url_save = now
        self._request_url_cache_save()

    def _request_url_cache_save(self) -> None:
        with self._url_cache_lock:
            if self._url_save_released:
                return
            self._url_save_dirty = True
            if (
                self._url_save_writer is not None
                and self._url_save_writer.is_alive()
            ):
                return

            def writer() -> None:
                while True:
                    with self._url_cache_lock:
                        if self._url_save_released:
                            return
                        dirty = self._url_save_dirty
                        if not dirty:
                            return
                        self._url_save_dirty = False
                    self._save_url_cache()
                    time.sleep(5.0)

            self._url_save_writer = threading.Thread(
                target=writer, name="mm-url-save", daemon=True
            )
            self._url_save_writer.start()

    def release_caches(self) -> None:
        """Drop URL cache files immediately after real exit."""
        with self._url_cache_lock:
            writer = self._url_save_writer
            self._url_save_dirty = True
            self._url_save_released = True
        if writer is not None:
            writer.join(timeout=2.0)
        with self._url_cache_lock:
            self._url_cache.clear()
            self._url_cache_dirty = False
            self._url_save_dirty = False
            self._url_save_writer = None
            self._last_url_save = 0.0
        self._delete_url_cache_file()

    def _delete_url_cache_file(self) -> None:
        for path in (
            self._url_cache_path,
            Path(str(self._url_cache_path) + ".tmp"),
        ):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

    def set_login(self, login: Dict[str, Any]) -> None:
        with self._state_lock:
            self._login = dict(login or {})
            self._save_login()

    def clear_login(self) -> None:
        with self._state_lock:
            self._login = {}
            try:
                if self._login_path.exists():
                    self._login_path.unlink()
            except Exception:
                pass

    def _request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        retries: int = 2,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(retries):
            url = self._base + path
            if params:
                url += "?" + urllib.parse.urlencode(params)
            request = urllib.request.Request(
                url,
                data=None if method == "GET" else b"",
                headers=self.auth_headers(),
                method=method,
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    start = raw.find("{")
                    if start < 0:
                        raise KugouAPIError("音乐接口返回了无法解析的数据")
                    data = json.loads(raw[start:])
                if data.get("status") == 2:
                    raise KugouAPIError("登录状态已失效，请重新登录")
                return data
            except urllib.error.HTTPError as exc:
                try:
                    raw = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    raw = ""
                if raw.strip():
                    try:
                        data = json.loads(raw)
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        start = raw.find("{")
                        if start >= 0:
                            try:
                                data = json.loads(raw[start:])
                                if isinstance(data, dict):
                                    return data
                            except json.JSONDecodeError:
                                pass
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(0.15 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(0.15 * (attempt + 1))
        if last_error is not None:
            raise KugouAPIError(f"音乐接口请求失败：{last_error}")
        raise KugouAPIError("音乐接口请求失败")

    def register_device(self) -> Dict[str, Any]:
        if self._device:
            return self._device
        data = self._request("/register/dev", retries=2)
        device = data.get("data") or {}
        with self._state_lock:
            self._device = dict(device)
        self._save_device()
        return self._device

    def fetch_rank_list(self) -> List[Dict[str, Any]]:
        data = self._request("/rank/list", retries=2)
        info = (data.get("data") or {}).get("info") or []
        result = []
        for item in info:
            result.append(
                {
                    "rankid": item.get("rankid"),
                    "rankname": item.get("rankname") or "未知榜单",
                    "cover": _cover(
                        item.get("img_9")
                        or item.get("album_img_9")
                        or item.get("banner_9")
                    ),
                    "play_times": item.get("play_times") or 0,
                }
            )
        return result

    def fetch_rank_songs(
        self, rankid: str, pagesize: int = 100, limit: int = 300
    ) -> List[Song]:
        songs: List[Song] = []
        seen: set[str] = set()
        page = 1
        while len(songs) < limit and page <= 3:
            data = self._request(
                "/rank/audio",
                {
                    "rankid": rankid,
                    "page": page,
                    "pagesize": min(pagesize, 100),
                },
                retries=2,
            )
            songlist = (data.get("data") or {}).get("songlist") or []
            for item in songlist:
                song = _song_from_rank(item)
                if song is not None and song.key not in seen:
                    seen.add(song.key)
                    songs.append(song)
            if len(songlist) < pagesize:
                break
            page += 1
        return songs[:limit]

    def fetch_lyrics(self, hash_value: str) -> List[LyricLine]:
        if not hash_value:
            return []
        try:
            search = self._request(
                "/search/lyric", {"hash": hash_value}, retries=2, timeout=15
            )
        except KugouAPIError:
            return []
        candidates = search.get("candidates") or []
        if not isinstance(candidates, list):
            return []

        def score(item: Dict[str, Any]) -> int:
            result = 0
            if item.get("product_from") == "官方推荐歌词":
                result += 3
            if not item.get("ugc"):
                result += 1
            if item.get("content_format") == 1:
                result += 1
            return -result

        candidates.sort(key=score)
        for candidate in candidates:
            lyric_id = candidate.get("id") or candidate.get("download_id") or ""
            accesskey = candidate.get("accesskey") or ""
            if not lyric_id:
                continue
            for fmt in ("krc", "lrc"):
                try:
                    data = self._request(
                        "/lyric",
                        {
                            "id": str(lyric_id),
                            "accesskey": accesskey,
                            "fmt": fmt,
                            "decode": "true",
                        },
                        retries=2,
                        timeout=12,
                    )
                except KugouAPIError:
                    continue
                content = data.get("decodeContent") or data.get("content") or ""
                lines = parse_lyrics(str(content))
                if lines:
                    return lines
        return []

    def fetch_new_songs(self, limit: int = 100) -> List[Song]:
        songs: List[Song] = []
        seen: set[str] = set()
        page = 1
        while len(songs) < limit and page <= 4:
            data = self._request(
                "/top/song", {"page": page, "pagesize": 30}, retries=2
            )
            items = data.get("data") or []
            for item in items:
                song = _song_from_top(item)
                if song is not None and song.key not in seen:
                    seen.add(song.key)
                    songs.append(song)
            if len(items) < 30:
                break
            page += 1
        return songs[:limit]

    def fetch_playlists(
        self, category_id: int = 0, limit: int = 12, page: int = 1
    ) -> List[AlbumCard]:
        cards: List[AlbumCard] = []
        seen: set[str] = set()
        current = max(1, page)
        while len(cards) < limit and current <= page + 3:
            data = self._request(
                "/top/playlist",
                {
                    "category_id": category_id,
                    "withsong": 0,
                    "page": current,
                    "pagesize": 35,
                },
                retries=2,
            )
            items = (data.get("data") or {}).get("special_list") or []
            for item in items:
                album_id = (
                    item.get("global_collection_id") or item.get("specialid") or ""
                )
                if not album_id or album_id in seen:
                    continue
                seen.add(album_id)
                cards.append(
                    AlbumCard(
                        title=item.get("specialname") or "未知歌单",
                        artist=item.get("nickname") or item.get("singername") or "",
                        cover_url=_cover(
                            item.get("flexible_cover")
                            or item.get("imgurl")
                            or item.get("pic")
                        ),
                        album_id=album_id,
                    )
                )
            if len(items) < 30:
                break
            current += 1
        return cards[:limit]

    def fetch_playlist_tracks(
        self, playlist_id: str, pagesize: int = 100, limit: int = 300
    ) -> List[Song]:
        songs: List[Song] = []
        seen: set[str] = set()
        page = 1
        while len(songs) < limit and page <= 5:
            data = self._request(
                "/playlist/track/all",
                {
                    "id": str(playlist_id),
                    "page": page,
                    "pagesize": pagesize,
                },
                retries=2,
            )
            songs_data = (data.get("data") or {}).get("songs") or []
            for item in songs_data:
                song = _song_from_playlist(item)
                if song is not None and song.key not in seen:
                    seen.add(song.key)
                    songs.append(song)
            count = int((data.get("data") or {}).get("count") or len(songs_data))
            if len(songs_data) < pagesize or len(songs) >= count:
                break
            page += 1
        return songs[:limit]

    def search_songs(self, term: str, limit: int = 50) -> Tuple[List[Song], str]:
        if not term.strip():
            return [], ""
        params = {"keywords": term, "page": 1, "pagesize": min(limit, 50), "type": 0}
        try:
            data = self._request("/search", params, retries=2, timeout=12)
        except KugouAPIError as exc:
            if "502" in str(exc) or "Bad Gateway" in str(exc):
                return self._search_mobile(term, limit)
            return self._search_mobile(term, limit)
        lists = (data.get("data") or {}).get("lists") or []
        songs = []
        seen: set[str] = set()
        for item in lists:
            song = _song_from_search(item)
            if song is not None and song.key not in seen:
                seen.add(song.key)
                songs.append(song)
        if songs:
            return songs[:limit], ""
        return self._search_mobile(term, limit)

    def _search_mobile(self, term: str, limit: int = 50) -> Tuple[List[Song], str]:
        url = "http://mobilecdn.kugou.com/api/v3/search/song?" + urllib.parse.urlencode(
            {"keyword": term, "page": 1, "pagesize": min(limit, 50)}
        )
        try:
            data = self._mobile_json(url)
        except KugouAPIError as exc:
            return [], f"搜索服务暂时不可用：{exc}"
        if data.get("status") != 1:
            return [], "搜索服务暂时不可用，请稍后重试"
        info = (data.get("data") or {}).get("info") or []
        songs = []
        seen: set[str] = set()
        for item in info:
            song = _song_from_search(item)
            if song is not None and song.key not in seen:
                seen.add(song.key)
                songs.append(song)
        return songs[:limit], ""

    def _mobile_json(self, url: str, timeout: float = 15.0, retries: int = 2) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(retries):
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Referer": "http://www.kugou.com/",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw)
            except Exception as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(0.15)
        raise KugouAPIError(f"音乐搜索接口请求失败：{last_error}")

    def _kugou_api_cookies(self) -> Dict[str, str]:
        """Fetch stable device identifiers from the local KuGou API."""
        with self._state_lock:
            cached = dict(self._device)
        required = ("mid", "guid", "serverDev", "mac", "dfid")
        if all(cached.get(key) for key in required) and cached.get("dfid") != "-":
            return {
                "mid": str(cached["mid"]),
                "guid": str(cached["guid"]),
                "dev": str(cached["serverDev"]),
                "mac": str(cached["mac"]),
                "dfid": str(cached["dfid"]),
            }
        query: Dict[str, str] = {}
        current_dfid = str(cached.get("dfid") or "")
        if current_dfid and current_dfid != "-":
            query["dfid"] = current_dfid
        url = self._base + "/register/dev"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "MeemawMusic/1.0"
                )
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read().decode("utf-8", errors="replace")
                cookie_headers = response.headers.get_all("Set-Cookie") or []
        except Exception as exc:
            raise KugouAPIError(f"读取设备信息失败：{exc}") from exc

        cookies: Dict[str, str] = {}
        for header in cookie_headers:
            for part in header.split(";"):
                part = part.strip()
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                cookies[name.strip()] = value.strip()

        dfid = ""
        try:
            body = json.loads(raw)
            data = body.get("data")
            if isinstance(data, dict):
                dfid = str(data.get("dfid") or "")
        except (json.JSONDecodeError, ValueError):
            pass
        if not dfid or dfid == "undefined":
            dfid = cookies.get("dfid") or ""
        if not dfid or dfid == "undefined":
            dfid = current_dfid
        if not dfid or dfid == "undefined":
            dfid = "-"

        result = {
            "mid": cookies.get("KUGOU_API_MID") or "",
            "guid": cookies.get("KUGOU_API_GUID") or "",
            "dev": cookies.get("KUGOU_API_DEV") or "",
            "mac": cookies.get("KUGOU_API_MAC") or "",
            "dfid": dfid,
        }
        with self._state_lock:
            self._device["mid"] = result["mid"] or self._device.get("mid", "")
            self._device["guid"] = result["guid"] or self._device.get("guid", "")
            self._device["serverDev"] = result["dev"] or self._device.get(
                "serverDev", ""
            )
            self._device["mac"] = result["mac"] or self._device.get("mac", "")
            self._device["dfid"] = dfid
        self._save_device()
        return result

    def qr_key(self) -> Dict[str, str]:
        """Create a KuGou concept edition scan login QR code."""
        data = self._request("/login/qr/key", retries=2, timeout=12)
        info = data.get("data") or {}
        key = str(info.get("qrcode") or "")
        image = str(info.get("qrcode_img") or "")
        if not key or not image:
            raise KugouAPIError("未获取到酷狗概念版登录二维码")
        return {"key": key, "image": image}

    def qr_check(self, key: str) -> Tuple[int, Dict[str, Any]]:
        """Poll a KuGou concept edition login session."""
        if not key:
            raise KugouAPIError("酷狗概念版登录会话已失效，请重新获取二维码")
        data = self._request(
            "/login/qr/check",
            {"key": key, "timestamp": int(time.time() * 1000)},
            retries=1,
            timeout=8,
        )
        info = data.get("data") or {}
        status = int(info.get("status") or 0)
        if status == 1:
            return 1, {"status": "wait", "msg": "等待扫码"}
        if status == 2:
            return 2, {"status": "scanned", "msg": "已扫码，请在酷狗概念版确认登录"}
        if status == 0:
            return 0, {"status": "expired", "msg": "二维码已失效"}
        if status == 4:
            payload = info
            login: Dict[str, Any] = {}
            for login_key in (
                "token",
                "userid",
                "t1",
                "vip_type",
                "vip_token",
                "vip_grade",
                "vip_expire",
                "vip_expire_time",
                "vip_days",
                "is_vip",
                "vip_begin",
                "vip_begin_time",
                "nickname",
                "user_name",
                "avatar",
                "photo_url",
            ):
                if payload.get(login_key) is not None:
                    login[login_key] = payload[login_key]
            if not login.get("token") or not login.get("userid"):
                raise KugouAPIError("登录成功但返回信息不完整")
            login.setdefault("nickname", login.get("user_name") or "网络用户")
            self.set_login(login)
            self._merge_member_info(payload)
            return 4, {"status": 4, "msg": "登录成功", **login}
        return 1, {"status": "wait", "msg": str(info.get("msg") or "等待扫码")}

    def validate_login(self) -> bool:
        if not self.logged_in:
            return False
        try:
            data = self._request("/user/detail", retries=1, timeout=12)
        except KugouAPIError as exc:
            if "登录状态已失效" in str(exc):
                return False
            raise
        code = int(data.get("error_code") or 0)
        if code in (20002, 51002) or data.get("status") == 2:
            return False
        return True

    def _merge_member_info(self, payload: Any) -> None:
        info = _extract_member_fields(payload)
        if not info:
            return
        with self._state_lock:
            self._login.update(info)
            self._login["member_synced_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_login()

    def sync_member_info(self) -> Tuple[bool, Dict[str, Any]]:
        """Refresh the logged-in account's VIP status and persist it locally."""
        if not self.logged_in:
            return False, {"message": "请先完成酷狗概念版扫码登录"}
        try:
            if not self.validate_login():
                return False, {"message": "登录状态已失效，请重新登录后再同步"}
        except KugouAPIError as exc:
            return False, {"message": f"同步会员信息失败：{exc}"}
        try:
            data = self._request("/user/vip/detail", retries=1, timeout=8)
        except KugouAPIError as exc:
            return False, {"message": f"同步会员信息失败：{exc}"}
        if isinstance(data, dict) and data.get("status") not in (None, 1):
            code = data.get("error_code")
            message = data.get("error_msg") or data.get("errmsg") or ""
            text = f"同步会员信息失败（错误码 {code}）" if code else "同步会员信息失败"
            if message:
                text += f"：{message}"
            return False, {"message": text}
        info = _extract_busi_vip(data)
        if info:
            with self._state_lock:
                self._login.update(info)
        with self._state_lock:
            self._login["member_synced_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_login()
        member_info = self.member_info
        if (
            info.get("vip_name")
            or member_info.get("is_vip")
            or member_info.get("vip_expire")
        ):
            message = "会员信息已同步"
        else:
            message = "已同步，暂未获取到会员数据"
        return True, {"message": message, **member_info}

    def resolve_song_url(
        self,
        hash_value: str,
        quality: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        if not hash_value:
            raise KugouAPIError("缺少歌曲标识")
        preferred = quality or self.quality or "320"
        cache_key = (str(hash_value), str(preferred))
        with self._url_cache_lock:
            cached = self._url_cache.get(cache_key)
            if (
                not force
                and cached is not None
                and time.time() - cached[0] < _URL_CACHE_TTL
            ):
                return cached[1]
        logged = self.logged_in
        candidates: List[Tuple[str, str]] = []
        if logged:
            try:
                data = self._request(
                    "/privilege/lite", {"hash": hash_value}, retries=1, timeout=6
                )
                privileges = data.get("data") or []
                if not isinstance(privileges, list):
                    privileges = []
                available: Dict[str, str] = {}
                for entry in privileges:
                    if entry.get("level") == 0:
                        continue
                    quality = entry.get("quality") or ""
                    if quality in QUALITY_ORDER:
                        available.setdefault(quality, entry.get("hash") or hash_value)
                if preferred in available:
                    candidates.append((available.pop(preferred), preferred))
                for item_quality in QUALITY_ORDER:
                    if item_quality in available:
                        candidates.append((available.pop(item_quality), item_quality))
                if not candidates and preferred in ("128", "320", "flac", "high"):
                    candidates = [(hash_value, "128")]
            except KugouAPIError:
                candidates = []
            if not candidates:
                candidates = [(hash_value, "128")]
        else:
            candidates = [(hash_value, "")]

        for play_hash, quality in candidates[:3]:
            params: Dict[str, Any] = {"hash": play_hash}
            if quality:
                params["quality"] = quality
                params["ppage_id"] = "356753938"
            else:
                params["free_part"] = 1
            try:
                data = self._request("/song/url", params, retries=1, timeout=6)
            except KugouAPIError:
                continue
            if data.get("status") != 1:
                continue
            if data.get("extName") == "mp4":
                continue
            url_list = data.get("url") or []
            if not url_list:
                continue
            result = {
                "url": url_list[0],
                "backup": data.get("backupUrl") or url_list[1:],
                "duration": _seconds(
                    data.get("timeLength")
                    or data.get("time_length")
                    or data.get("timelength")
                    or 0
                ),
                "quality": quality or "128",
                "raw": data,
            }
            with self._url_cache_lock:
                self._url_cache[cache_key] = (time.time(), result)
                self._url_cache_dirty = True
                if len(self._url_cache) > 256:
                    oldest_key = min(
                        self._url_cache, key=lambda key: self._url_cache[key][0]
                    )
                    del self._url_cache[oldest_key]
            self._maybe_save_url_cache()
            return result
        raise KugouAPIError(
            "获取音乐地址失败"
            if logged
            else "未登录只能播放试听片段，请先完成酷狗概念版扫码登录"
        )

    def fetch_discover(self, page: int = 1) -> Dict[str, List[Any]]:
        playlists = self.fetch_playlists(0, 12, page=page)
        songs = self.fetch_new_songs(36)
        banners = []
        for song in songs[:3]:
            banners.append(
                BannerItem(
                    title=song.title,
                    subtitle=f"{song.artist} · 网络新歌热榜",
                    cover_url=song.cover_url,
                    song=song,
                )
            )
        return {"playlists": playlists, "songs": songs, "banners": banners}


def default_client() -> KugouClient:
    global _default
    if _default is None:
        _default = KugouClient()
    return _default


_default: Optional[KugouClient] = None
