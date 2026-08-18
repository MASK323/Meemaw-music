from __future__ import annotations

from collections import deque
from typing import Dict, List

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

_MAX_CACHE = 160
_MAX_EDGE = 512
_MAX_INFLIGHT = 8


class ImageLoader(QObject):
    loaded = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._manager.setTransferTimeout(10000)
        self._manager.finished.connect(self._on_finished)
        self._pending: Dict[QNetworkReply, str] = {}
        self._waiters: Dict[str, List[str]] = {}
        self._active: Dict[str, List[str]] = {}
        self._queue: deque[str] = deque()
        self._cache: Dict[str, QImage] = {}

    def load(self, token: str, url: str) -> None:
        if not url:
            return
        cached = self._cache.get(url)
        if cached is not None:
            QTimer.singleShot(0, lambda: self.loaded.emit(token, cached))
            return
        waiters = self._waiters.get(url)
        if waiters is not None:
            if token not in waiters:
                waiters.append(token)
            return
        self._waiters[url] = [token]
        self._queue.append(url)
        self._pump()

    def _pump(self) -> None:
        while len(self._active) < _MAX_INFLIGHT and self._queue:
            url = self._queue.popleft()
            tokens = self._waiters.get(url)
            if not tokens:
                continue
            self._active[url] = tokens
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(b"User-Agent", b"MeemawMusic/1.0")
            request.setRawHeader(b"Accept", b"image/*")
            reply = self._manager.get(request)
            self._pending[reply] = url

    def load_bytes(self, token: str, data: bytes) -> None:
        image = QImage()
        if image.loadFromData(data):
            self.loaded.emit(token, image)

    def _on_finished(self, reply: QNetworkReply) -> None:
        url = self._pending.pop(reply, None)
        data = bytes(reply.readAll())
        reply.deleteLater()
        if url is None:
            self._pump()
            return
        tokens = self._active.pop(url, [])
        self._waiters.pop(url, None)
        image = QImage()
        if image.loadFromData(data):
            if image.width() > _MAX_EDGE or image.height() > _MAX_EDGE:
                image = image.scaled(
                    _MAX_EDGE,
                    _MAX_EDGE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._cache[url] = image
            if len(self._cache) > _MAX_CACHE:
                self._cache.pop(next(iter(self._cache)))
            for token in tokens:
                self.loaded.emit(token, image)
        self._pump()
