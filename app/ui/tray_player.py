from __future__ import annotations

import bisect
from typing import List, Optional

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QSystemTrayIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.core.models import LyricLine, Song
from app.ui.icons import IconButton


def _wrap_fit_text(text: str, font, max_width: int, max_lines: int = 3) -> str:
    fm = QFontMetrics(font)
    paragraphs = str(text or "").split("\n")
    lines: List[str] = []
    for paragraph in paragraphs:
        current = ""
        for word in paragraph.split(" "):
            if current:
                candidate = current + " " + word
                if fm.horizontalAdvance(candidate) <= max_width:
                    current = candidate
                    continue
                lines.append(current)
                current = word
            else:
                current = word
            while fm.horizontalAdvance(current) > max_width and len(current) > 1:
                cut = 1
                for i in range(2, len(current) + 1):
                    if fm.horizontalAdvance(current[:i]) > max_width:
                        break
                    cut = i
                lines.append(current[:cut])
                current = current[cut:]
        if current:
            lines.append(current)
    if not lines:
        lines.append("")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        suffix = "..."
        while last and fm.horizontalAdvance(last + suffix) > max_width:
            last = last[:-1]
        lines[-1] = last + suffix
    return "\n".join(lines)


class TrayProgress(QSlider):
    seek_requested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("trayProgress")
        self.setRange(0, 0)
        self.setFixedHeight(18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dragging = False

    def _ratio_to_value(self, x: float) -> int:
        if self.maximum() <= self.minimum():
            return self.minimum()
        ratio = max(0.0, min(1.0, x / max(1, self.width())))
        return self.minimum() + int(round((self.maximum() - self.minimum()) * ratio))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > 0:
            self._dragging = True
            self.setValue(self._ratio_to_value(event.position().x()))
            self.seek_requested.emit(self.value())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self.maximum() > 0:
            self.setValue(self._ratio_to_value(event.position().x()))
            self.seek_requested.emit(self.value())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)


class MenuRow(QWidget):
    clicked = Signal(str)

    def __init__(
        self,
        key: str,
        icon: str,
        label: str,
        checked: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("trayMenuRow")
        self._key = key
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(10)

        self._icon = IconButton(icon, size=18)
        self._icon.set_icon_color(QColor("#c9ccd1"))
        self._icon.setEnabled(False)
        layout.addWidget(self._icon)

        self._label = QLabel(label)
        self._label.setObjectName("trayMenuText")
        layout.addWidget(self._label)

        self._check = QLabel("")
        self._check.setObjectName("trayMenuCheck")
        self._check.setFixedWidth(22)
        self._check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if checked:
            self._check.setText("✓")
        layout.addWidget(self._check)
        layout.addStretch(1)

        arrow = QLabel("›")
        arrow.setObjectName("trayMenuArrow")
        arrow.setFixedWidth(14)
        arrow.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(arrow)

        self._hovered = False

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._label.setStyleSheet("color: #ffffff; font-weight: 600;")
        self._icon.set_icon_color(QColor("#ffffff"))
        self.setStyleSheet("#trayMenuRow { background: rgba(255,255,255,0.08); border-radius: 10px; }")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._label.setStyleSheet("")
        self._icon.set_icon_color(QColor("#c9ccd1"))
        self.setStyleSheet("")
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class TrayPlayerPopup(QWidget):
    play_toggled = Signal()
    next_requested = Signal()
    prev_requested = Signal()
    like_toggled = Signal()
    seek_requested = Signal(int)
    menu_clicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Popup
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("trayPlayerPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Meemaw music")
        self.resize(310, 452)

        self._liked = False
        self._song: Optional[Song] = None
        self._seeking = False
        self._lines: List[LyricLine] = []
        self._starts: List[int] = []
        self._tooltip_line = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("trayPlayerCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(10)
        note = IconButton("note", size=30)
        note.set_icon_color(QColor("#ec4141"))
        note.setEnabled(False)
        header.addWidget(note)

        info_box = QVBoxLayout()
        info_box.setSpacing(2)
        self._title = QLabel("未在播放")
        self._title.setObjectName("traySongTitle")
        self._title.setWordWrap(True)
        self._title.setMaximumWidth(240)
        info_box.addWidget(self._title)
        self._artist = QLabel("选择一首歌曲开始播放")
        self._artist.setObjectName("traySongArtist")
        self._artist.setMaximumWidth(240)
        info_box.addWidget(self._artist)
        header.addLayout(info_box, 1)
        layout.addLayout(header)

        layout.addSpacing(12)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(0)
        self._progress = TrayProgress()
        self._progress.seek_requested.connect(self._on_progress_seek)
        progress_row.addWidget(self._progress, 1)
        layout.addLayout(progress_row)

        layout.addSpacing(12)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addStretch(1)
        self._prev = IconButton("prev", size=28)
        self._prev.set_icon_color(QColor("#ffffff"))
        self._prev.clicked.connect(self.prev_requested.emit)
        controls.addWidget(self._prev)

        self._play = IconButton("play", size=42)
        self._play.set_solid_background(QColor("#ec4141"))
        self._play.set_icon_color(QColor("#ffffff"))
        self._play.clicked.connect(self.play_toggled.emit)
        controls.addWidget(self._play)

        self._next = IconButton("next", size=28)
        self._next.set_icon_color(QColor("#ffffff"))
        self._next.clicked.connect(self.next_requested.emit)
        controls.addWidget(self._next)

        self._like = IconButton("heart", size=28)
        self._like.set_icon_color(QColor("#ec4141"))
        self._like.clicked.connect(self.like_toggled.emit)
        controls.addWidget(self._like)
        controls.addStretch(1)
        layout.addLayout(controls)

        layout.addSpacing(12)

        line = QFrame()
        line.setObjectName("trayDivider")
        line.setFixedHeight(1)
        layout.addWidget(line)
        layout.addSpacing(8)

        for key, icon, label in (
            ("shuffle", "shuffle", "随机播放"),
            ("full", "maximize", "完整模式"),
            ("desktop_music", "desktop", "开启音乐桌面"),
            ("desktop_lyric", "lyric", "打开桌面歌词"),
            ("settings", "settings", "设置"),
            ("exit", "logout", "退出"),
        ):
            row = MenuRow(key, icon, label)
            row.clicked.connect(self._on_menu_row)
            layout.addWidget(row)
            if key == "desktop_lyric":
                row._check.setText("")
                self._lyric_row = row

        layout.addSpacing(6)
        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        brand = QLabel("Meemaw music")
        brand.setObjectName("trayBrand")
        footer.addWidget(brand)
        footer.addStretch(1)
        layout.addLayout(footer)

        root.addWidget(card)
        self._desktop_lyrics_checked = False

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#2a2522"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 18, 18)

    def _on_progress_seek(self, value: int) -> None:
        self.seek_requested.emit(value)

    def _on_menu_row(self, key: str) -> None:
        self.menu_clicked.emit(key)

    def set_song(self, song: Optional[Song], liked: bool = False) -> None:
        self._song = song
        self._liked = bool(liked)
        self._lines = []
        self._starts = []
        self._tooltip_line = -1
        if song is None:
            self._title.setText("未在播放")
            self._artist.setText("选择一首歌曲开始播放")
        else:
            self._title.setText(_wrap_fit_text(song.title, self._title.font(), 230))
            self._artist.setText(_wrap_fit_text(song.artist, self._artist.font(), 230))
        self._like.set_icon("heart_fill" if self._liked else "heart")
        self.setToolTip(song.title if song is not None else "Meemaw music")

    def set_state(self, state: str) -> None:
        self._play.set_icon("pause" if state == "playing" else "play")

    def set_position(self, position_ms: int) -> None:
        if not self.isVisible():
            return
        if not self._seeking:
            self._progress.blockSignals(True)
            self._progress.setValue(int(position_ms))
            self._progress.blockSignals(False)
        if self._lines:
            current = max(0, bisect.bisect_right(self._starts, position_ms) - 1)
            if current != self._tooltip_line and current < len(self._lines):
                self._tooltip_line = current
                self.setToolTip(self._lines[current].text)

    def set_duration(self, duration_ms: int) -> None:
        self._progress.blockSignals(True)
        self._progress.setMaximum(max(0, duration_ms))
        self._progress.setValue(min(self._progress.value(), max(0, duration_ms)))
        self._progress.blockSignals(False)

    def set_lyrics(self, lines: List[LyricLine]) -> None:
        self._lines = list(lines or [])
        self._starts = [line.start_ms for line in self._lines]
        self._tooltip_line = -1

    def set_liked(self, liked: bool) -> None:
        self._liked = bool(liked)
        self._like.set_icon("heart_fill" if self._liked else "heart")

    def set_desktop_lyric_checked(self, checked: bool) -> None:
        self._desktop_lyrics_checked = bool(checked)
        if hasattr(self, "_lyric_row"):
            self._lyric_row._check.setText("✓" if checked else "")

    def show_near_tray(self, tray: Optional[QSystemTrayIcon] = None) -> None:
        screen = QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)

        tray_geo = QRect()
        if tray is not None and QSystemTrayIcon.isSystemTrayAvailable():
            tray_geo = tray.geometry()
        x = geometry.right() - self.width() - 18
        y = geometry.bottom() - self.height() - 12
        if tray_geo.isValid() and not tray_geo.isEmpty():
            x = tray_geo.left() - self.width() - 14
            y = tray_geo.top() - self.height() - 14
            if x < geometry.left():
                x = tray_geo.right() + 14
            if y < geometry.top():
                y = geometry.top() + 14
        self.move(max(geometry.left() + 8, x), max(geometry.top() + 8, y))
        self.show()
        self.raise_()
        self.activateWindow()

        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(160)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


class DesktopLyricsWindow(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("desktopLyrics")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(520, 90)
        self._lines: List[LyricLine] = []
        self._starts: List[int] = []
        self._current = -1
        self._song_title = "未在播放"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        self._label = QLabel("未在播放")
        self._label.setObjectName("desktopLyricText")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            "color: rgba(255,255,255,235); font-size: 22px; font-weight: 700;"
            "background: rgba(20,18,17,180); border-radius: 18px; padding: 12px 22px;"
        )
        layout.addWidget(self._label)
        self._drag_offset: Optional[QPoint] = None

    def set_song(self, song: Optional[Song]) -> None:
        self._lines = []
        self._starts = []
        self._current = -1
        if song is None:
            self._song_title = "未在播放"
            self._label.setText("未在播放")
        else:
            self._song_title = song.title
            self._label.setText(song.title)

    def set_lyrics(self, lines: List[LyricLine]) -> None:
        self._lines = list(lines or [])
        self._starts = [line.start_ms for line in self._lines]
        self._current = -1
        self._label.setText(self._song_title)

    def set_position(self, position_ms: int) -> None:
        if not self._lines:
            return
        current = max(0, bisect.bisect_right(self._starts, position_ms) - 1)
        if current != self._current and 0 <= current < len(self._lines):
            self._current = current
            self._label.setText(self._lines[current].text)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
