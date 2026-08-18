from __future__ import annotations

import bisect
import html
import math
import os
import time
from typing import Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QElapsedTimer,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.models import LyricLine, Song, format_duration
from app.ui.icons import ACCENT, IconButton


def _make_cover_icon(image: Optional[QImage], size: int = 44) -> QIcon:
    if image is not None and not image.isNull():
        pixmap = QPixmap.fromImage(image).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QIcon(pixmap)
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#2a2a30"))
    return QIcon(pixmap)


class RoundedRowDelegate(QStyledItemDelegate):
    def __init__(self, view: "SongTable", parent=None) -> None:
        super().__init__(parent)
        self._view = view

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if index.column() == 0:
            viewport = self._view.viewport()
            row_rect = QRectF(
                4,
                option.rect.top() + 3,
                max(0, viewport.width() - 8),
                max(0, option.rect.height() - 6),
            )
            selected = option.state & QStyle.StateFlag.State_Selected
            hovered = option.state & QStyle.StateFlag.State_MouseOver
            if selected:
                fill = QColor(236, 65, 65, 30)
            elif hovered:
                fill = QColor(255, 255, 255, 13)
            elif index.row() % 2 == 0:
                fill = QColor(255, 255, 255, 4)
            else:
                fill = QColor(255, 255, 255, 0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(row_rect, 14, 14)
        painter.restore()
        super().paint(painter, option, index)


class SongTable(QTableWidget):
    play_requested = Signal(object, int)
    like_toggled = Signal(object)

    def __init__(self, image_loader, parent: Optional[QWidget] = None) -> None:
        super().__init__(0, 6, parent)
        self.setObjectName("songTable")
        self.setItemDelegate(RoundedRowDelegate(self))
        self._image_loader = image_loader
        self._songs: List[Song] = []
        self._liked_keys: set[str] = set()
        self._tokens: Dict[str, int] = {}
        self._playable_flags: List[bool] = []
        self._duration_flags: List[float] = []
        self._heart_buttons: List[tuple[IconButton, Song]] = []

        self.setHorizontalHeaderLabels(["#", "标题", "歌手", "专辑", "时长", "喜欢"])
        header = self.horizontalHeader()
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        for col, width in ((0, 48), (2, 150), (3, 180), (4, 72), (5, 48)):
            header.setSectionResizeMode(col, header.ResizeMode.Fixed)
            self.setColumnWidth(col, width)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(56)
        self.setShowGrid(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAlternatingRowColors(False)
        self.cellDoubleClicked.connect(self._on_double_click)
        self._image_loader.loaded.connect(self._on_image_loaded)

    def set_songs(self, songs: List[Song], liked_keys: Optional[set[str]] = None) -> None:
        self._songs = list(songs)
        self._playable_flags = [
            bool(song.kugou_hash or song.url or song.local_path)
            for song in self._songs
        ]
        self._duration_flags = [float(song.duration or 0) for song in self._songs]
        if liked_keys is not None:
            self._liked_keys = set(liked_keys)
        self._tokens.clear()
        self._heart_buttons.clear()
        self.setRowCount(0)
        self.setRowCount(len(self._songs))

        for row, song in enumerate(self._songs):
            rank_item = QTableWidgetItem(str(row + 1))
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            rank_item.setForeground(QColor("#ec4141") if row < 3 else QColor("#7d8087"))
            self.setItem(row, 0, rank_item)

            cover_image = None
            if song.cover_data:
                cover_image = QImage()
                cover_image.loadFromData(song.cover_data)
            playable = bool(song.kugou_hash or song.url or song.local_path)
            title_item = QTableWidgetItem(_make_cover_icon(cover_image), song.title)
            title_item.setForeground(QColor("#ffffff") if playable else QColor("#777b82"))
            if not playable:
                title_item.setToolTip("暂无网络音源，无法播放")
            self.setItem(row, 1, title_item)

            artist_item = QTableWidgetItem(song.artist)
            artist_item.setForeground(QColor("#8f9299"))
            self.setItem(row, 2, artist_item)

            album_item = QTableWidgetItem(song.album or "-")
            album_item.setForeground(QColor("#8f9299"))
            self.setItem(row, 3, album_item)

            time_item = QTableWidgetItem(song.time_text())
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setForeground(QColor("#8f9299"))
            self.setItem(row, 4, time_item)

            heart = IconButton("heart_fill" if song.key in self._liked_keys else "heart", size=26)
            heart.set_icon_color(QColor("#ec4141"))
            heart.clicked.connect(lambda checked=False, s=song: self.like_toggled.emit(s))
            self.setCellWidget(row, 5, heart)
            self._heart_buttons.append((heart, song))

            token = f"table:{id(self)}:{row}:{song.key}"
            self._tokens[token] = row
            if song.cover_url:
                self._image_loader.load(token, song.cover_url)
            elif song.cover_data:
                self._image_loader.load_bytes(token, song.cover_data)

    def update_playability(self) -> None:
        """Refresh only the rows whose playable state or duration changed."""
        if len(self._songs) != self.rowCount():
            return
        changed = False
        for row, song in enumerate(self._songs):
            playable = bool(song.kugou_hash or song.url or song.local_path)
            if (
                row >= len(self._playable_flags)
                or self._playable_flags[row] != playable
            ):
                if row >= len(self._playable_flags):
                    self._playable_flags.append(playable)
                else:
                    self._playable_flags[row] = playable
                title_item = self.item(row, 1)
                if title_item is not None:
                    title_item.setForeground(
                        QColor("#ffffff") if playable else QColor("#777b82")
                    )
                    title_item.setToolTip(
                        "" if playable else "暂无网络音源，无法播放"
                    )
                changed = True
            duration = float(song.duration or 0)
            if (
                row >= len(self._duration_flags)
                or abs(self._duration_flags[row] - duration) > 0.001
            ):
                if row >= len(self._duration_flags):
                    self._duration_flags.append(duration)
                else:
                    self._duration_flags[row] = duration
                time_item = self.item(row, 4)
                if time_item is not None:
                    time_item.setText(song.time_text())
                changed = True
        if changed:
            self.viewport().update()

    def set_liked_keys(self, liked_keys: set[str]) -> None:
        self._liked_keys = set(liked_keys)
        for heart, song in self._heart_buttons:
            heart.set_icon("heart_fill" if song.key in self._liked_keys else "heart")

    def songs(self) -> List[Song]:
        return list(self._songs)

    def _on_double_click(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._songs):
            self.play_requested.emit(self._songs, row)

    def _on_image_loaded(self, token: str, image: QImage) -> None:
        row = self._tokens.get(token)
        if row is None:
            return
        item = self.item(row, 1)
        if item is not None:
            item.setIcon(_make_cover_icon(image))


class QueuePanel(QFrame):
    play_at = Signal(int)
    remove_at = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("queuePanel")
        self.setFixedWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 10)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("播放队列")
        title.setObjectName("sectionTitle")
        self._count = QLabel("0 首")
        self._count.setObjectName("subText")
        clear_button = QPushButton("清空")
        clear_button.setObjectName("textButton")
        clear_button.clicked.connect(self._on_clear)
        header.addWidget(title)
        header.addWidget(self._count)
        header.addStretch(1)
        header.addWidget(clear_button)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setObjectName("queueList")
        self._list.itemDoubleClicked.connect(self._on_play)
        layout.addWidget(self._list, 1)

    def set_queue(self, songs: List[Song], current_index: int = -1) -> None:
        self._list.clear()
        for index, song in enumerate(songs):
            item = QListWidgetItem(song.display)
            item.setData(Qt.ItemDataRole.UserRole, index)
            if index == current_index:
                item.setForeground(QColor("#ec4141"))
                font = QFont()
                font.setBold(True)
                item.setFont(font)
            self._list.addItem(item)
        self._count.setText(f"{len(songs)} 首")

    def _on_play(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int):
            self.play_at.emit(index)

    def _on_clear(self) -> None:
        if self._list.count():
            self._list.clear()
            self._count.setText("0 首")
            self.remove_at.emit(-1)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            row = self._list.currentRow()
            if row >= 0:
                self.remove_at.emit(row)
            return
        super().keyPressEvent(event)


class SeekSlider(QSlider):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._press_seeking = False
        self._hovered = False
        self._feedback = 0.0
        self._feedback_anim = QVariantAnimation(self)
        self._feedback_anim.setDuration(110)
        self._feedback_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._feedback_anim.valueChanged.connect(
            lambda value: self._set_feedback(float(value))
        )
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_feedback(self, value: float) -> None:
        self._feedback = max(0.0, min(1.0, value))
        self.update()

    def _animate_feedback(self, target: float) -> None:
        self._feedback_anim.stop()
        self._feedback_anim.setStartValue(self._feedback)
        self._feedback_anim.setEndValue(target)
        self._feedback_anim.start()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._animate_feedback(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._animate_feedback(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(0.0, float(self.width()))
        height = max(0.0, float(self.height()))
        center_y = height / 2.0
        feedback = max(self._feedback, 1.0 if self._press_seeking else 0.0)
        groove_height = 4.0 + 2.0 * feedback
        groove_rect = QRectF(0.0, center_y - groove_height / 2.0, width, groove_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3a3430"))
        painter.drawRoundedRect(groove_rect, groove_height / 2.0, groove_height / 2.0)

        progress_width = groove_height
        if self.maximum() > self.minimum():
            ratio = (self.value() - self.minimum()) / float(self.maximum() - self.minimum())
            progress_width = max(groove_height, width * max(0.0, min(1.0, ratio)))
            progress_rect = QRectF(
                groove_rect.left(),
                groove_rect.top(),
                progress_width,
                groove_rect.height(),
            )
            painter.setBrush(QColor("#fd3d4f"))
            painter.drawRoundedRect(
                progress_rect,
                groove_height / 2.0,
                groove_height / 2.0,
            )
        if feedback > 0.01:
            thumb_center = QPointF(
                groove_rect.left() + progress_width,
                center_y,
            )
            thumb_radius = 5.5 + 1.5 * feedback
            painter.setPen(QPen(QColor(0, 0, 0, 70), 1.0))
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(thumb_center, thumb_radius, thumb_radius)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            value = self._value_from_pos(event.position().x())
            self.setValue(value)
            self._press_seeking = True
            self.sliderPressed.emit()
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_seeking:
            value = self._value_from_pos(event.position().x())
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._press_seeking:
            self._press_seeking = False
            self.sliderReleased.emit()
            self._animate_feedback(1.0 if self._hovered else 0.0)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _value_from_pos(self, x: float) -> int:
        width = max(1, self.width())
        ratio = min(1.0, max(0.0, x / width))
        return self.minimum() + int(round((self.maximum() - self.minimum()) * ratio))


class VolumeSliderBar(QWidget):
    value_changed = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(16)
        self.setMinimumHeight(96)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value = 50
        self._hovered = False
        self._dragging = False
        self._feedback = 0.0
        self._pulse = 0.0
        self._feedback_anim = QVariantAnimation(self)
        self._feedback_anim.setDuration(120)
        self._feedback_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._feedback_anim.valueChanged.connect(
            lambda value: self._set_feedback(float(value))
        )
        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setDuration(150)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pulse_anim.valueChanged.connect(
            lambda value: self._set_pulse(float(value))
        )
        self._pulse_out = QVariantAnimation(self)
        self._pulse_out.setDuration(260)
        self._pulse_out.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._pulse_out.valueChanged.connect(
            lambda value: self._set_pulse(float(value))
        )

    def _set_feedback(self, value: float) -> None:
        self._feedback = max(0.0, min(1.0, value))
        self.update()

    def _set_pulse(self, value: float) -> None:
        self._pulse = max(0.0, min(1.0, value))
        self.update()

    def _animate_feedback(self, target: float) -> None:
        self._feedback_anim.stop()
        self._feedback_anim.setStartValue(self._feedback)
        self._feedback_anim.setEndValue(target)
        self._feedback_anim.start()

    def _bump_pulse(self) -> None:
        self._pulse_out.stop()
        self._pulse_anim.stop()
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.finished.connect(
            self._pulse_fall, Qt.ConnectionType.UniqueConnection
        )
        self._pulse_anim.start()

    def _pulse_fall(self) -> None:
        self._pulse_out.setStartValue(self._pulse)
        self._pulse_out.setEndValue(0.0)
        self._pulse_out.start()

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        if value != self._value:
            self._value = value
            if not self._dragging:
                self._bump_pulse()
            self.value_changed.emit(value)
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._animate_feedback(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._animate_feedback(0.0)
        super().leaveEvent(event)

    def _value_from_pos(self, y: float) -> int:
        usable = max(1.0, float(self.height()) - 14.0)
        ratio = 1.0 - (max(0.0, min(float(self.height()), y)) - 7.0) / usable
        return int(round(max(0.0, min(1.0, ratio)) * 100.0))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.set_value(self._value_from_pos(event.position().y()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.set_value(self._value_from_pos(event.position().y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self._bump_pulse()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        self.set_value(self._value + (5 if delta > 0 else -5))
        event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(0.0, float(self.width()))
        center_x = width / 2.0
        feedback = self._feedback
        track_width = 2.5 + 0.7 * feedback
        track_rect = QRectF(
            center_x - track_width / 2.0,
            7.0,
            track_width,
            max(0.0, float(self.height()) - 14.0),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#423b36"))
        painter.drawRoundedRect(track_rect, track_width / 2.0, track_width / 2.0)

        progress_height = track_width
        if self.height() > 14:
            progress_height = max(
                track_width,
                track_rect.height() * max(0.0, min(1.0, self._value / 100.0)),
            )
        fill_rect = QRectF(
            track_rect.left(),
            track_rect.bottom() - progress_height,
            track_rect.width(),
            progress_height,
        )
        painter.setBrush(QColor("#fd3d4f"))
        fill_gradient = QLinearGradient(
            fill_rect.topLeft(), fill_rect.bottomLeft()
        )
        fill_gradient.setColorAt(0.0, QColor("#ff6b78"))
        fill_gradient.setColorAt(0.35, QColor("#fd3d4f"))
        fill_gradient.setColorAt(1.0, QColor("#d92a3b"))
        painter.setBrush(fill_gradient)
        painter.drawRoundedRect(fill_rect, track_width / 2.0, track_width / 2.0)

        thumb_center = QPointF(
            center_x,
            track_rect.bottom() - progress_height,
        )
        thumb_radius = 4.0 + 1.6 * feedback
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1.0))
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(thumb_center, thumb_radius, thumb_radius)


class VolumeControl(QWidget):
    volume_changed = Signal(float)

    def __init__(self, size: int = 28, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value = 0.5
        self._hover_control = False
        self._hover_popup = False
        self._popup: Optional[QFrame] = None
        self._slider: Optional[VolumeSliderBar] = None
        self._percent: Optional[QLabel] = None
        self._app_filter_active = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._icon = IconButton("volume", size=size)
        self._icon.set_icon_color(QColor("#ffffff"))
        self._icon.setToolTip("音量")
        self._icon.clicked.connect(self._toggle_popup)
        layout.addWidget(self._icon)

    def set_volume(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._value = value
        if self._slider is not None:
            self._slider.blockSignals(True)
            self._slider.set_value(int(round(value * 100.0)))
            self._slider.blockSignals(False)
        if self._percent is not None:
            self._percent.setText(f"{int(round(value * 100.0))}%")
        self.update()

    def showEvent(self, event) -> None:
        self._ensure_popup()
        super().showEvent(event)

    def enterEvent(self, event) -> None:
        self._hover_control = True
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_control = False
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        self._hover_control = False
        self._hover_popup = False
        if self._popup is not None:
            self._popup.hide()
        self._release_app_filter()
        super().hideEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        self.set_volume(self._value + (0.05 if delta > 0 else -0.05))
        self.volume_changed.emit(self._value)
        event.accept()

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and self._popup is not None
            and self._popup.isVisible()
        ):
            pos = event.globalPosition().toPoint()
            popup_rect = QRect(
                self._popup.mapToGlobal(QPoint(0, 0)), self._popup.size()
            )
            icon_rect = QRect(
                self._icon.mapToGlobal(QPoint(0, 0)), self._icon.size()
            )
            if not popup_rect.contains(pos) and not icon_rect.contains(pos):
                self._popup.hide()
                self._release_app_filter()
        elif watched is self._popup:
            if event.type() == QEvent.Type.Enter:
                self._hover_popup = True
            elif event.type() == QEvent.Type.Leave:
                self._hover_popup = False
        return super().eventFilter(watched, event)

    def _ensure_popup(self) -> None:
        if self._popup is not None:
            return
        parent = self.window() or self
        popup = QFrame(parent)
        popup.setObjectName("volumePopup")
        popup.setFixedSize(54, 158)
        popup.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        popup.installEventFilter(self)
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(7, 6, 7, 6)
        popup_layout.setSpacing(5)
        self._percent = QLabel("50%")
        self._percent.setObjectName("volumePercent")
        self._percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        popup_layout.addWidget(self._percent)
        self._slider = VolumeSliderBar(popup)
        self._slider.set_value(int(round(self._value * 100.0)))
        self._slider.value_changed.connect(self._on_slider_changed)
        popup_layout.addWidget(self._slider, 1, Qt.AlignmentFlag.AlignHCenter)
        self._popup_icon = IconButton("volume", size=22)
        self._popup_icon.set_icon_color(QColor("#ffffff"))
        self._popup_icon.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._popup_icon.setCursor(Qt.CursorShape.ArrowCursor)
        self._popup_icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        popup_layout.addWidget(
            self._popup_icon, 0, Qt.AlignmentFlag.AlignHCenter
        )
        popup.hide()
        self._popup = popup

    def _show_popup(self) -> None:
        self._ensure_popup()
        popup = self._popup
        if popup is None:
            return
        parent = self.window() or self
        if popup.parent() is not parent:
            popup.setParent(parent)
        icon_pos = self._icon.mapTo(parent, QPoint(0, 0))
        x = round(icon_pos.x() + self._icon.width() / 2.0 - popup.width() / 2.0)
        y = icon_pos.y() - popup.height() - 4
        if parent is not self:
            x = max(8, min(x, parent.width() - popup.width() - 8))
            y = max(8, y)
        popup.move(x, y)
        popup.raise_()
        popup.show()
        app = QApplication.instance()
        if app is not None and not self._app_filter_active:
            app.installEventFilter(self)
            self._app_filter_active = True

    def _toggle_popup(self) -> None:
        self._ensure_popup()
        popup = self._popup
        if popup is not None and popup.isVisible():
            popup.hide()
            self._release_app_filter()
        else:
            self._show_popup()

    def _release_app_filter(self) -> None:
        if not self._app_filter_active:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._app_filter_active = False

    def _on_slider_changed(self, value: int) -> None:
        self._value = max(0.0, min(1.0, value / 100.0))
        if self._percent is not None:
            self._percent.setText(f"{value}%")
        self.volume_changed.emit(self._value)


_VINYL_DISC_CACHE: Optional[QPixmap] = None


def _vinyl_disc_source() -> QPixmap:
    global _VINYL_DISC_CACHE
    if _VINYL_DISC_CACHE is None:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "vinyl",
            "disc.png",
        )
        if os.path.exists(path):
            _VINYL_DISC_CACHE = QPixmap(path)
        else:
            _VINYL_DISC_CACHE = QPixmap()
    return _VINYL_DISC_CACHE


class VinylDisc(QFrame):
    """A smooth rotating vinyl with a white center label and tonearm."""

    def __init__(
        self,
        size: int = 120,
        needle: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size
        self._image: Optional[QImage] = None
        self._label_text = ""
        self._angle = 0.0
        self._spinning = False
        self._spin_speed = 0.0
        self._spin_target = 0.0
        self._spin_last_ns = 0
        self._needle = needle
        self._dirty = True
        self._cache = QPixmap()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._elapsed = QElapsedTimer()
        self._needle_angle = 62.0
        self._needle_target = 62.0
        self._needle_start_angle = 62.0
        self._needle_timer = QTimer(self)
        self._needle_timer.setInterval(16)
        self._needle_timer.timeout.connect(self._tick_needle)
        self._needle_elapsed = QElapsedTimer()
        self._needle_last_ns = 0
        self._transition_suppress_paint = False

    def set_size(self, size: int) -> None:
        size = max(48, int(size))
        if size == self._size:
            return
        # During page transitions the live page is re-rendered every frame.
        # Resizing here would rebuild the vinyl cache repeatedly and the disc
        # size feeds back into the page layout, so freeze it until the
        # transition finishes.
        if self._transition_suppress_paint:
            return
        self._size = size
        self.setFixedSize(size, size)
        self._dirty = True
        if not self._transition_suppress_paint:
            self.update()

    def set_spinning(self, spinning: bool) -> None:
        if spinning == self._spinning:
            return
        self._spinning = spinning
        self._spin_target = 45.0 if spinning else 0.0
        if not self._timer.isActive():
            self._spin_last_ns = self._elapsed.nsecsElapsed()
            self._timer.start()
        if not self._transition_suppress_paint:
            self.update()

    def set_needle_visible(self, visible: bool) -> None:
        if visible != self._needle:
            self._needle = visible
            if not visible:
                self._needle_timer.stop()
            if not self._transition_suppress_paint:
                self.update()

    def set_needle_active(self, active: bool) -> None:
        if not self._needle:
            return
        target = 2.5 if active else 62.0
        if abs(target - self._needle_target) < 0.01:
            return
        self._needle_target = target
        self._needle_start_angle = self._needle_angle
        self._needle_elapsed.restart()
        self._needle_last_ns = self._needle_elapsed.nsecsElapsed()
        if not self._needle_timer.isActive():
            self._needle_timer.start()
        if not self._transition_suppress_paint:
            self.update()

    def set_transition_mode(self, active: bool) -> None:
        """Advance animation state without emitting repaints while active.

        The transition overlay renders the page itself, so the disc must keep
        its angle moving but must not schedule its own paint events during the
        transition.  This avoids the covered page flashing or fighting the
        overlay's live cache.
        """
        active = bool(active)
        if active == self._transition_suppress_paint:
            return
        self._transition_suppress_paint = active
        if active:
            if not self._timer.isActive() and (self._spinning or self._spin_speed > 0.05):
                self._spin_last_ns = self._elapsed.nsecsElapsed()
                self._timer.start()
        else:
            self.update()

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._dirty = True
        if not self._transition_suppress_paint:
            self.update()

    def set_label_text(self, text: str) -> None:
        text = str(text or "")
        if text != self._label_text:
            self._label_text = text
            self._dirty = True
            if not self._transition_suppress_paint:
                self.update()

    def set_cover_data(self, data: bytes) -> None:
        image = QImage()
        if image.loadFromData(data):
            self.set_image(image)

    def hideEvent(self, event) -> None:
        # Keep the rotation timers alive while hidden so player page
        # transitions never freeze the spinning record.
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        if not self._timer.isActive() and (self._spinning or self._spin_speed > 0.05):
            self._spin_last_ns = self._elapsed.nsecsElapsed()
            self._timer.start()
        if (
            self._needle
            and not self._needle_timer.isActive()
            and abs(self._needle_angle - self._needle_target) > 0.01
        ):
            self._needle_elapsed.restart()
            self._needle_timer.start()
        super().showEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            win = self.window()
            if win.isMinimized():
                self._timer.stop()
                self._needle_timer.stop()
            elif not self._timer.isActive() and (
                self._spinning or self._spin_speed > 0.05
            ):
                self._spin_last_ns = self._elapsed.nsecsElapsed()
                self._timer.start()
        super().changeEvent(event)

    def _tick(self) -> None:
        now_ns = self._elapsed.nsecsElapsed()
        if self._spin_last_ns == 0:
            delta = 0.0
        else:
            delta = min(
                0.08,
                max(0.0, (now_ns - self._spin_last_ns) / 1_000_000_000.0),
            )
        self._spin_last_ns = now_ns
        if delta > 0.0:
            alpha = 1.0 - math.exp(-delta / 0.14)
            self._spin_speed += (self._spin_target - self._spin_speed) * alpha
            self._angle = (self._angle + self._spin_speed * delta) % 360.0
            if not self._spinning and self._spin_speed < 0.12:
                self._spin_speed = 0.0
                self._timer.stop()
        if not self._transition_suppress_paint:
            self.update()

    def _tick_needle(self) -> None:
        now = self._needle_elapsed.nsecsElapsed()
        elapsed = max(0.0, now / 1_000_000_000.0)
        duration = 0.22
        t = min(1.0, elapsed / duration)
        eased = 1.0 - (1.0 - t) * (1.0 - t) * (1.0 - t)
        self._needle_angle = self._needle_start_angle + (
            self._needle_target - self._needle_start_angle
        ) * eased
        if t >= 1.0:
            self._needle_angle = self._needle_target
            self._needle_timer.stop()
        if not self._transition_suppress_paint:
            self.update()

    def _ensure_cache(self) -> None:
        if self._dirty or self._cache.isNull() or self._cache.size() != QSize(self._size, self._size):
            self._cache = self._render_disc(self._size)
            self._dirty = False

    def _render_disc(self, size: int) -> QPixmap:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        center = QPointF(size / 2.0, size / 2.0)
        disc_radius = size / 2.0 - 1.0
        clip_path = QPainterPath()
        clip_path.addEllipse(center, disc_radius, disc_radius)
        painter.save()
        painter.setClipPath(clip_path)

        cover = self._image
        base = QRadialGradient(center, disc_radius)
        base.setColorAt(0.0, QColor("#404040"))
        base.setColorAt(0.30, QColor("#262626"))
        base.setColorAt(0.75, QColor("#101010"))
        base.setColorAt(1.0, QColor("#030303"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base)
        painter.drawEllipse(center, disc_radius, disc_radius)
        source = _vinyl_disc_source()
        if not source.isNull():
            painter.drawPixmap(
                QRectF(0, 0, size, size),
                source,
                QRectF(0, 0, source.width(), source.height()),
            )
        groove_pen_light = QPen(QColor(255, 255, 255, 22), max(0.6, size * 0.001))
        groove_pen_light.setCosmetic(True)
        groove_pen_dark = QPen(QColor(0, 0, 0, 80), max(0.6, size * 0.001))
        groove_pen_dark.setCosmetic(True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        groove_count = max(28, min(80, int(size * 0.15)))
        for index in range(groove_count):
            ratio = 0.68 + index * (0.305 / max(1, groove_count - 1))
            painter.setPen(groove_pen_light if index % 2 == 0 else groove_pen_dark)
            painter.drawEllipse(center, disc_radius * ratio, disc_radius * ratio)
        painter.setPen(QPen(QColor(255, 255, 255, 36), max(0.9, size * 0.002)))
        painter.drawEllipse(center, disc_radius * 0.985, disc_radius * 0.985)

        label_radius = disc_radius * 0.67
        label_rect = QRectF(
            center.x() - label_radius,
            center.y() - label_radius,
            label_radius * 2.0,
            label_radius * 2.0,
        )
        label_path = QPainterPath()
        label_path.addEllipse(label_rect)
        painter.save()
        painter.setClipPath(label_path)
        if cover is not None and not cover.isNull():
            painter.drawImage(
                label_rect,
                cover.scaled(
                    int(label_rect.width()),
                    int(label_rect.height()),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )
            painter.fillPath(label_path, QColor(0, 0, 0, 55))
        else:
            label_gradient = QRadialGradient(center, label_radius)
            label_gradient.setColorAt(0.0, QColor("#fefdf9"))
            label_gradient.setColorAt(0.78, QColor("#f5f0e6"))
            label_gradient.setColorAt(1.0, QColor("#e8e1d2"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(label_gradient)
            painter.drawEllipse(label_rect)
            texture_pen = QPen(QColor(90, 82, 70, 20), 0.6)
            painter.setPen(texture_pen)
            step = max(2, int(size * 0.008))
            for y in range(int(label_rect.top()), int(label_rect.bottom()), step):
                painter.drawLine(
                    QPointF(label_rect.left(), y),
                    QPointF(label_rect.right(), y),
                )
        painter.restore()

        painter.setPen(QPen(QColor(232, 228, 220, 170), max(1.0, size * 0.0024)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, label_radius, label_radius)

        if self._label_text and size >= 90:
            font = QFont("KaiTi")
            font.setFamilies(["KaiTi", "Microsoft YaHei"])
            font.setPixelSize(max(10, min(int(label_radius * 0.34), int(size * 0.085))))
            metrics = QFontMetrics(font)
            text = self._label_text.strip()
            max_width = int(label_radius * 1.7)
            if metrics.horizontalAdvance(text) > max_width:
                while text and metrics.horizontalAdvance(text + "…") > max_width:
                    text = text[:-1]
                text += "…"
            text_rect = QRectF(
                center.x() - label_radius * 0.95,
                center.y() - label_radius * 0.95,
                label_radius * 1.9,
                label_radius * 1.9,
            )
            painter.setFont(font)
            painter.setPen(QColor("#1c1712"))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

        sheen = QRadialGradient(
            center.x() - disc_radius * 0.42,
            center.y() - disc_radius * 0.48,
            disc_radius * 1.35,
        )
        sheen.setColorAt(0.0, QColor(255, 255, 255, 24))
        sheen.setColorAt(0.4, QColor(255, 255, 255, 5))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(sheen)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, disc_radius, disc_radius)

        painter.restore()
        painter.end()
        return pixmap

    def _draw_needle(self, painter: QPainter, size: int) -> None:
        pivot = QPointF(size * 0.50, size * 0.030)
        arm_len = size * 0.560
        raised_angle = 35.0
        lowered_angle = 72.0
        spread = max(0.001, 62.0 - 2.5)
        t = min(1.0, max(0.0, (62.0 - self._needle_angle) / spread))
        t = 1.0 - (1.0 - t) * (1.0 - t) * (1.0 - t)
        arm_angle = raised_angle + (lowered_angle - raised_angle) * t

        painter.save()
        painter.translate(pivot)
        painter.rotate(arm_angle)
        arm = QPen(QColor("#f4efe6"), max(1.6, size * 0.016))
        arm.setCapStyle(Qt.PenCapStyle.RoundCap)
        arm.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(arm)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(0.0, 0.0))
        path.cubicTo(
            QPointF(arm_len * 0.42, -size * 0.012),
            QPointF(arm_len * 0.82, size * 0.016),
            QPointF(arm_len, 0.0),
        )
        painter.drawPath(path)

        pivot_radius = max(2.2, size * 0.022)
        painter.setPen(QPen(QColor(0, 0, 0, 110), 1.0))
        painter.setBrush(QColor("#f7f2e9"))
        painter.drawEllipse(QPointF(0.0, 0.0), pivot_radius, pivot_radius)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(
            QPointF(0.0, 0.0),
            max(1.2, pivot_radius * 0.45),
            max(1.2, pivot_radius * 0.45),
        )

        cartridge = QRectF(
            arm_len - size * 0.052,
            -size * 0.012,
            size * 0.052,
            size * 0.024,
        )
        painter.setPen(QPen(QColor(0, 0, 0, 100), 1.0))
        painter.setBrush(QColor("#fbf7ef"))
        painter.drawRoundedRect(cartridge, size * 0.004, size * 0.004)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#403a34"))
        painter.drawEllipse(
            QPointF(arm_len + size * 0.004, 0.0),
            size * 0.005,
            size * 0.005,
        )
        painter.setBrush(QColor("#c9c2b6"))
        painter.drawEllipse(
            QPointF(arm_len - size * 0.010, 0.0),
            size * 0.004,
            size * 0.004,
        )
        painter.restore()

    def resizeEvent(self, event) -> None:
        if self.width() != self._size or self.height() != self._size:
            self._size = min(self.width(), self.height())
            self._dirty = True
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        if self.width() <= 1 or self.height() <= 1:
            return
        self._ensure_cache()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        painter.save()
        painter.translate(center)
        painter.rotate(self._angle)
        painter.translate(-center)
        painter.drawPixmap(
            QRectF(0, 0, self.width(), self.height()),
            self._cache,
            QRectF(0, 0, self._cache.width(), self._cache.height()),
        )
        painter.restore()
        if self._needle:
            self._draw_needle(painter, self.width())


class LyricView(QWidget):
    """Custom-painted centered lyrics with a current-line time badge."""

    seek_requested = Signal(int)

    ROW_HEIGHT = 56
    FONT_NORMAL = 16
    FONT_ACTIVE = 24

    @staticmethod
    def _format_time(ms: int) -> str:
        seconds = max(0, ms // 1000)
        if seconds >= 3600:
            return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("lyricList")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self._lines: List[LyricLine] = []
        self._starts: List[int] = []
        self._starts_sorted = True
        self._current_row = -1
        self._hover_row = -1
        self._scroll = 0.0
        self._scroll_target = 0.0
        self._manual_scrolling = False
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_scroll)
        self._wheel_anim = QVariantAnimation(self)
        self._wheel_anim.setDuration(220)
        self._wheel_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._wheel_anim.valueChanged.connect(self._on_wheel_value)
        self._wheel_anim.finished.connect(self._on_wheel_finished)
        self._time_visible = False
        self._time_hide_timer = QTimer(self)
        self._time_hide_timer.setSingleShot(True)
        self._time_hide_timer.setInterval(1200)
        self._time_hide_timer.timeout.connect(self._hide_time_badge)
        self._transition_suppress_paint = False

    def sizeHint(self) -> QSize:
        return QSize(320, 240)

    def hideEvent(self, event) -> None:
        self._anim_timer.stop()
        if self._time_hide_timer.isActive():
            self._time_hide_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        if self._current_row >= 0:
            self._target_current_row()
        if self._time_visible and not self._time_hide_timer.isActive():
            self._time_hide_timer.start()
        super().showEvent(event)

    def set_transition_mode(self, active: bool) -> None:
        """Keep scroll state advancing without repainting during transitions."""
        active = bool(active)
        if active == self._transition_suppress_paint:
            return
        self._transition_suppress_paint = active
        if active:
            if self._wheel_anim.state() == QVariantAnimation.State.Running:
                self._wheel_anim.pause()
            if (
                self._anim_timer.isActive()
                or abs(self._scroll_target - self._scroll) > 0.4
            ):
                if not self._anim_timer.isActive():
                    self._anim_timer.start()
        else:
            if self._wheel_anim.state() == QVariantAnimation.State.Paused:
                self._wheel_anim.resume()
            self.update()

    def set_lines(self, lines: List[LyricLine]) -> None:
        self._lines = list(lines or [])
        self._starts = [line.start_ms for line in self._lines]
        self._starts_sorted = all(
            self._starts[i] <= self._starts[i + 1]
            for i in range(max(0, len(self._starts) - 1))
        )
        self._current_row = -1
        self._scroll = 0.0
        self._scroll_target = 0.0
        self._manual_scrolling = False
        self._anim_timer.stop()
        self._wheel_anim.stop()
        self._time_visible = False
        self._time_hide_timer.stop()
        if not self._transition_suppress_paint:
            self.update()
        self.updateGeometry()

    def set_position(self, position_ms: int) -> None:
        if not self._lines:
            return
        if self._starts_sorted:
            current = max(0, bisect.bisect_right(self._starts, position_ms) - 1)
        else:
            current = 0
            for index, start in enumerate(self._starts):
                if start <= position_ms:
                    current = index
                else:
                    break
        if current == self._current_row:
            return
        self._current_row = current
        if not self._manual_scrolling:
            self._wheel_anim.stop()
        self._target_current_row()
        if not self._transition_suppress_paint:
            self.update()

    def _on_wheel_value(self, value) -> None:
        self._scroll = max(0.0, float(value))
        if not self._transition_suppress_paint:
            self.update()

    def _on_wheel_finished(self) -> None:
        self._scroll_target = self._scroll
        self._manual_scrolling = False
        if not self._transition_suppress_paint:
            self.update()

    def _content_height(self) -> int:
        return len(self._lines) * self.ROW_HEIGHT

    def _time_rect(self, row: int) -> QRectF:
        y = row * self.ROW_HEIGHT - self._scroll
        side = 26.0
        return QRectF(
            self.width() - 66.0,
            y + (self.ROW_HEIGHT - side) / 2.0,
            50.0,
            side,
        )

    def _row_at(self, pos: QPointF) -> int:
        if self.height() <= 0:
            return -1
        row = int((pos.y() + self._scroll) / self.ROW_HEIGHT)
        if row < 0 or row >= len(self._lines):
            return -1
        return row

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        row = self._row_at(pos)
        if row != self._hover_row:
            self._hover_row = row
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if row >= 0
                else Qt.CursorShape.ArrowCursor
            )
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_row != -1:
            self._hover_row = -1
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            row = self._row_at(event.position())
            if row >= 0:
                self.seek_requested.emit(self._lines[row].start_ms)
                event.accept()
                return
        super().mousePressEvent(event)

    def _target_current_row(self) -> None:
        if self._manual_scrolling:
            return
        height = self.height()
        if height <= 0 or self._current_row < 0:
            return
        center_y = self._current_row * self.ROW_HEIGHT + self.ROW_HEIGHT / 2.0
        max_scroll = max(0, self._content_height() - height)
        self._scroll_target = min(
            max(0.0, center_y - height / 2.0),
            float(max_scroll),
        )
        if abs(self._scroll_target - self._scroll) > 0.5:
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        else:
            self._scroll = self._scroll_target

    def _tick_scroll(self) -> None:
        diff = self._scroll_target - self._scroll
        if abs(diff) < 0.4:
            self._scroll = self._scroll_target
            self._anim_timer.stop()
        else:
            self._scroll += diff * 0.22
        if not self._transition_suppress_paint:
            self.update()

    def _hide_time_badge(self) -> None:
        if self._time_visible:
            self._time_visible = False
            if not self._transition_suppress_paint:
                self.update()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta:
            self._time_visible = True
            self._time_hide_timer.start()
            self._manual_scrolling = True
            max_scroll = max(0, self._content_height() - self.height())
            target = min(
                max(0.0, self._scroll - delta * 0.35),
                float(max_scroll),
            )
            self._wheel_anim.stop()
            self._wheel_anim.setStartValue(self._scroll)
            self._wheel_anim.setEndValue(target)
            self._wheel_anim.start()
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._target_current_row()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        width = self.width()
        height = self.height()
        if not self._lines:
            font = QFont(self.font())
            font.setPixelSize(self.FONT_NORMAL)
            painter.setFont(font)
            painter.setPen(QColor("#7d8087"))
            painter.drawText(
                QRectF(0.0, 0.0, width, height),
                Qt.AlignmentFlag.AlignCenter,
                "纯音乐，请欣赏",
            )
            return
        for index, line in enumerate(self._lines):
            y = index * self.ROW_HEIGHT - self._scroll
            if y + self.ROW_HEIGHT < 0 or y > height:
                continue
            rect = QRectF(12.0, y, max(120.0, width - 88.0), self.ROW_HEIGHT)
            if index == self._current_row:
                self._paint_active(painter, rect, line.text)
            else:
                font = QFont(self.font())
                font.setPixelSize(self.FONT_NORMAL)
                metrics = QFontMetrics(font)
                text = metrics.elidedText(
                    line.text,
                    Qt.TextElideMode.ElideRight,
                    max(40, int(rect.width()) - 8),
                )
                painter.setFont(font)
                painter.setPen(QColor("#9a9da4"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            if index == self._current_row and self._time_visible:
                self._paint_time_badge(painter, index, y)

    def _paint_active(self, painter: QPainter, rect: QRectF, text: str) -> None:
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(self.FONT_ACTIVE)
        metrics = QFontMetrics(font)
        text = metrics.elidedText(
            text,
            Qt.TextElideMode.ElideRight,
            max(40, int(rect.width()) - 12),
        )
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_time_badge(self, painter: QPainter, row: int, y: float) -> None:
        rect = self._time_rect(row)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(70, 70, 70, 235))
        painter.drawRoundedRect(rect, 13.0, 13.0)

        cx = rect.left() + 10.0
        cy = rect.center().y()
        triangle = QPainterPath(QPointF(cx - 2.5, cy - 4.0))
        triangle.lineTo(QPointF(cx + 3.5, cy))
        triangle.lineTo(QPointF(cx - 2.5, cy + 4.0))
        triangle.closeSubpath()
        painter.setBrush(QColor(225, 225, 225))
        painter.drawPath(triangle)

        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor("#e2e2e2"))
        text = self._format_time(self._lines[row].start_ms)
        text_rect = QRectF(
            rect.left() + 14.0,
            rect.top(),
            rect.width() - 15.0,
            rect.height(),
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )


class LyricsPanel(QFrame):
    seek_requested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("lyricsPanel")
        self.setFixedWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(8)

        self._title = QLabel("暂无歌曲")
        self._title.setObjectName("songTitle")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._artist = QLabel("")
        self._artist.setObjectName("artistText")
        self._artist.setWordWrap(True)
        layout.addWidget(self._artist)

        self._lyrics = LyricView()
        self._lyrics.seek_requested.connect(self.seek_requested)
        layout.addWidget(self._lyrics, 1)

    def set_song(self, song: Optional[Song]) -> None:
        if song is None:
            self._title.setText("暂无歌曲")
            self._artist.setText("")
            self._lyrics.set_lines([])
            return
        self._title.setText(song.title)
        self._artist.setText(song.artist)
        self._lyrics.set_lines([])

    def set_lyrics(self, lines: List[LyricLine]) -> None:
        self._lyrics.set_lines(lines)

    def set_position(self, position_ms: int) -> None:
        self._lyrics.set_position(position_ms)


class RichCommentDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._doc_cache = {}
        self._doc_keys = []

    def _document(self, text: str, width: float, font) -> QTextDocument:
        key = (str(text), int(width))
        doc = self._doc_cache.get(key)
        if doc is not None:
            return doc
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setDocumentMargin(0)
        doc.setHtml(str(text))
        doc.setTextWidth(max(1.0, float(width)))
        self._doc_cache[key] = doc
        self._doc_keys.append(key)
        if len(self._doc_keys) > 96:
            self._doc_cache.pop(self._doc_keys.pop(0), None)
        return doc

    def paint(self, painter, option, index) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not text:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        doc = self._document(
            text,
            max(1.0, float(option.rect.width())),
            option.font,
        )
        painter.translate(option.rect.topLeft())
        doc.documentLayout().draw(
            painter, QAbstractTextDocumentLayout.PaintContext()
        )
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not text:
            return super().sizeHint(option, index)
        doc = self._document(text, 288.0, option.font)
        return QSize(300, int(doc.size().height()) + 12)


class CommentsPanel(QFrame):
    load_more_requested = Signal()

    @staticmethod
    def _format_comment_time(ts) -> str:
        try:
            ts = int(ts or 0)
        except (TypeError, ValueError):
            return ""
        if ts <= 0:
            return ""
        if ts > 10**11:
            ts = ts // 1000
        try:
            return time.strftime("%m-%d %H:%M", time.localtime(ts))
        except (OSError, OverflowError, ValueError):
            return ""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("commentsPanel")
        self.setFixedWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("评论")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        self._count = QLabel("0 条")
        self._count.setObjectName("subText")
        header.addWidget(self._count)
        header.addStretch(1)
        layout.addLayout(header)

        self._song_title = QLabel("暂无歌曲")
        self._song_title.setObjectName("songTitle")
        self._song_title.setWordWrap(True)
        layout.addWidget(self._song_title)

        self._status = QLabel("选择歌曲后查看评论")
        self._status.setObjectName("subText")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(90)
        layout.addWidget(self._status)

        self._list = QListWidget()
        self._list.setObjectName("commentList")
        self._list.setWordWrap(True)
        self._list.setItemDelegate(RichCommentDelegate(self._list))
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.verticalScrollBar().valueChanged.connect(
            self._check_scroll_bottom
        )
        layout.addWidget(self._list, 1)
        self._comment_items: List[Dict] = []

        self._more_footer = QLabel("")
        self._more_footer.setObjectName("commentMoreText")
        self._more_footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._more_footer.setWordWrap(True)
        self._more_footer.hide()
        layout.addWidget(self._more_footer)

    def set_song(self, song: Optional[Song]) -> None:
        self._list.clear()
        self._comment_items.clear()
        self._count.setText("0 条")
        self._more_footer.hide()
        if song is None:
            self._song_title.setText("暂无歌曲")
            self._set_status("选择歌曲后查看评论")
            return
        self._song_title.setText(song.title)
        self._set_status("评论加载中…")

    def set_loading(self) -> None:
        self._list.clear()
        self._comment_items.clear()
        self._count.setText("0 条")
        self._more_footer.hide()
        self._set_status("评论加载中…")

    def set_empty(self, message: str = "暂无评论") -> None:
        self._list.clear()
        self._comment_items.clear()
        self._count.setText("0 条")
        self._more_footer.hide()
        self._set_status(message)

    def set_comments(self, comments: List[Dict]) -> None:
        self._list.clear()
        self._comment_items.clear()
        self._more_footer.hide()
        if not comments:
            self._count.setText("0 条")
            self._set_status("暂无评论")
            return
        self._count.setText(f"{len(comments)} 条")
        self._status.hide()
        self._list.show()
        self._append_items(comments)

    def append_comments(self, comments: List[Dict]) -> None:
        if not comments:
            return
        self._status.hide()
        self._list.show()
        self._append_items(comments)
        self._count.setText(f"{self._list.count()} 条")

    def comments(self) -> List[Dict]:
        return list(self._comment_items)

    def set_loading_more(self) -> None:
        self._more_footer.setText("加载更多评论中…")
        self._more_footer.show()

    def set_more_error(self, message: str = "加载失败，继续下拉可重试") -> None:
        self._more_footer.setText(message)
        self._more_footer.show()

    def set_has_more(self, has_more: bool) -> None:
        if has_more:
            self._more_footer.hide()
        elif self._list.count() > 0:
            self._more_footer.setText("已经到底啦")
            self._more_footer.show()

    def _append_items(self, comments: List[Dict]) -> None:
        self._list.setUpdatesEnabled(False)
        try:
            for item in comments:
                self._comment_items.append(item)
                nickname = html.escape(str(item.get("nickname") or "匿名用户"))
                content = html.escape(str(item.get("content") or ""))
                liked = int(item.get("liked") or 0)
                time_text = self._format_comment_time(item.get("time"))
                meta = f"赞 {liked}"
                if time_text:
                    meta += f" · {time_text}"
                text = (
                    f"<div style='color:#ffffff; font-size:13px; font-weight:700;'>{nickname}</div>"
                    f"<div style='color:#b7bac1; font-size:12px; margin-top:3px;'>{content}</div>"
                    f"<div style='color:#7d8087; font-size:11px; margin-top:4px;'>{meta}</div>"
                )
                self._list.addItem(QListWidgetItem(text))
        finally:
            self._list.setUpdatesEnabled(True)

    def _check_scroll_bottom(self, value: int) -> None:
        if not self.isVisible() or not self._list.isVisible():
            return
        scrollbar = self._list.verticalScrollBar()
        if scrollbar.maximum() <= 0:
            return
        if value >= scrollbar.maximum() - 80:
            self.load_more_requested.emit()

    def _set_status(self, message: str) -> None:
        self._status.setText(message)
        self._status.show()
        self._list.hide()


class PlayerBar(QFrame):
    clicked = Signal()
    play_mode_changed = Signal(str)
    play_toggled = Signal()
    next_requested = Signal()
    prev_requested = Signal()
    queue_toggled = Signal()
    like_toggled = Signal()
    comment_toggled = Signal()
    volume_changed = Signal(float)
    seek_requested = Signal(int)
    lyric_toggled = Signal()

    def __init__(self, image_loader, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("playerBar")
        self.setFixedHeight(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._image_loader = image_loader
        self._click_targets: set = set()
        self._seeking = False
        self._cover_token = "player_cover"
        self._hovered = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(2)

        progress = QHBoxLayout()
        progress.setContentsMargins(4, 0, 4, 0)
        progress.setSpacing(10)
        self._time = QLabel("00:00")
        self._time.setObjectName("timeText")
        self._time.setFixedWidth(44)
        progress.addWidget(self._time)

        self._seek = SeekSlider()
        self._seek.setRange(0, 0)
        self._seek.setMinimumWidth(120)
        self._seek.sliderPressed.connect(self._on_seek_pressed)
        self._seek.sliderReleased.connect(self._on_seek_released)
        self._seek.sliderMoved.connect(self._on_seek_moved)
        progress.addWidget(self._seek, 1)

        self._duration = QLabel("00:00")
        self._duration.setObjectName("timeText")
        self._duration.setFixedWidth(44)
        self._duration.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        progress.addWidget(self._duration)
        layout.addLayout(progress)

        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)

        self._cover = VinylDisc(size=52)
        row.addWidget(self._cover)

        info_box = QVBoxLayout()
        info_box.setSpacing(4)
        self._song_title = QLabel("未在播放")
        self._song_title.setObjectName("songTitle")
        self._song_title.setMinimumWidth(110)
        self._artist = QLabel("选择一个音乐源开始播放")
        self._artist.setObjectName("artistText")
        self._artist.setMinimumWidth(110)
        info_box.addWidget(self._song_title)
        info_box.addWidget(self._artist)
        row.addLayout(info_box)
        self._click_targets = {self._cover, self._song_title, self._artist}

        self._like = IconButton("heart", size=26)
        self._like.set_icon_color(QColor("#ffffff"))
        self._like.clicked.connect(self.like_toggled.emit)
        self._like.setToolTip("喜欢")
        self._like_count = 0
        row.addWidget(self._like)

        self._comment = IconButton("comment", size=26)
        self._comment.set_icon_color(QColor("#ffffff"))
        self._comment.setToolTip("评论")
        self._comment.clicked.connect(self.comment_toggled.emit)
        row.addWidget(self._comment)

        row.addStretch(1)

        self._play_mode = IconButton("order", size=26)
        self._play_mode.set_icon_color(QColor("#ffffff"))
        self._play_mode.setToolTip("顺序播放")
        self._play_mode.clicked.connect(self._cycle_play_mode)
        row.addWidget(self._play_mode)

        self._prev = IconButton("prev", size=30)
        self._prev.set_icon_color(QColor("#ffffff"))
        self._prev.setToolTip("上一首")
        self._prev.clicked.connect(self.prev_requested.emit)
        row.addWidget(self._prev)

        self._play = IconButton("play", size=44)
        self._play.set_solid_background(QColor("#ff3333"))
        self._play.set_icon_color(QColor("#ffffff"))
        self._play.setToolTip("播放 / 暂停")
        self._play.clicked.connect(self.play_toggled.emit)
        row.addWidget(self._play)

        self._next = IconButton("next", size=30)
        self._next.set_icon_color(QColor("#ffffff"))
        self._next.setToolTip("下一首")
        self._next.clicked.connect(self.next_requested.emit)
        row.addWidget(self._next)

        row.addStretch(1)

        self._queue = IconButton("queue", size=28)
        self._queue.set_icon_color(QColor("#ffffff"))
        self._queue.setToolTip("播放队列")
        self._queue.clicked.connect(self.queue_toggled.emit)
        row.addWidget(self._queue)

        self._volume = VolumeControl(size=28)
        self._volume.volume_changed.connect(self.volume_changed.emit)
        row.addWidget(self._volume)

        self._lyric = IconButton("lyric", size=28)
        self._lyric.set_icon_color(QColor("#ffffff"))
        self._lyric.setToolTip("歌词")
        self._lyric.clicked.connect(self.lyric_toggled.emit)
        row.addWidget(self._lyric)
        layout.addLayout(row)

        self._toast = QLabel("")
        self._toast.setObjectName("artistText")
        self._toast.setStyleSheet("color: #ec4141;")
        self._toast.setMaximumWidth(220)
        self._toast.hide()
        row.addWidget(self._toast)

        self._image_loader.loaded.connect(self._on_image_loaded)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QColor(43, 37, 32, 246))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 20, 20)

    def mouseReleaseEvent(self, event) -> None:
        target = self.childAt(event.position().toPoint())
        if (
            event.button() == Qt.MouseButton.LeftButton
            and (target is None or target is self or target in self._click_targets)
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_song(self, song: Optional[Song], liked: bool = False) -> None:
        if song is None:
            self._song_title.setText("未在播放")
            self._artist.setText("选择一个音乐源开始播放")
            self._cover.set_image(QImage())
            self._cover.set_label_text("")
            self._like.setToolTip("喜欢")
            return
        self._song_title.setText(song.title)
        self._artist.setText(song.artist)
        self._cover.set_label_text(song.title)
        self._like.set_icon("heart_fill" if liked else "heart")
        if self._like_count > 0:
            self._like.setToolTip(f"喜欢 {self._like_count}")
        else:
            self._like.setToolTip("喜欢")
        if song.cover_data:
            image = QImage()
            if image.loadFromData(song.cover_data):
                self._set_cover_image(image)
        elif song.cover_url:
            self._image_loader.load(self._cover_token, song.cover_url)

    def set_like_count(self, count: int) -> None:
        self._like_count = max(0, int(count or 0))
        if self._like_count > 0:
            self._like.setToolTip(f"喜欢 {self._like_count}")
        else:
            self._like.setToolTip("喜欢")

    def set_state(self, state: str) -> None:
        self._play.set_icon("pause" if state == "playing" else "play")
        self._cover.set_spinning(state == "playing")
        self._cover.set_needle_active(state == "playing")

    def set_position(self, position_ms: int) -> None:
        if not self._seeking:
            value = max(0, int(position_ms))
            if value != self._seek.value():
                self._seek.blockSignals(True)
                self._seek.setValue(value)
                self._seek.blockSignals(False)
        text = format_duration(position_ms / 1000.0)
        if self._time.text() != text:
            self._time.setText(text)

    def set_duration(self, duration_ms: int) -> None:
        self._seek.blockSignals(True)
        self._seek.setMaximum(max(0, duration_ms))
        self._seek.setValue(min(self._seek.value(), max(0, duration_ms)))
        self._seek.blockSignals(False)
        text = format_duration(duration_ms / 1000.0)
        if self._duration.text() != text:
            self._duration.setText(text)

    def set_play_mode(self, mode: str) -> None:
        icons = {
            "order": "order",
            "list": "repeat",
            "one": "repeat_one",
            "shuffle": "shuffle",
        }
        labels = {
            "order": "顺序播放",
            "list": "列表循环",
            "one": "单曲循环",
            "shuffle": "随机播放",
        }
        mode = mode if mode in icons else "order"
        self._play_mode.set_icon(icons[mode])
        self._play_mode.setToolTip(labels[mode])

    def _cycle_play_mode(self) -> None:
        modes = ["order", "list", "one", "shuffle"]
        labels = {
            "顺序播放": "order",
            "列表循环": "list",
            "单曲循环": "one",
            "随机播放": "shuffle",
        }
        current_key = labels.get(self._play_mode.toolTip(), "order")
        next_key = modes[(modes.index(current_key) + 1) % len(modes)]
        self.set_play_mode(next_key)
        self.play_mode_changed.emit(next_key)

    def set_volume(self, value: float) -> None:
        self._volume.set_volume(value)

    def show_toast(self, message: str) -> None:
        self._toast.setText(message)
        self._toast.show()
        from PySide6.QtCore import QTimer

        QTimer.singleShot(4000, self._toast.hide)

    def _set_cover_image(self, image: QImage) -> None:
        self._cover.set_image(image)

    def _on_image_loaded(self, token: str, image: QImage) -> None:
        if token == self._cover_token:
            self._set_cover_image(image)

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _on_seek_released(self) -> None:
        self._seeking = False
        self.seek_requested.emit(self._seek.value())

    def _on_seek_moved(self, value: int) -> None:
        self._time.setText(format_duration(value / 1000.0))
        self.seek_requested.emit(value)


class CoverCard(QFrame):
    clicked = Signal()

    def __init__(self, cover_size: int = 150, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(cover_size + 18)
        self._cover_size = cover_size
        self._image: Optional[QImage] = None
        self._title_text = ""
        self._subtitle_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 10)
        layout.setSpacing(6)
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(cover_size, cover_size)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._cover_label)
        self._title = QLabel()
        self._title.setFixedWidth(cover_size)
        self._title.setWordWrap(False)
        self._title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 600;")
        layout.addWidget(self._title)
        self._subtitle = QLabel()
        self._subtitle.setFixedWidth(cover_size)
        self._subtitle.setStyleSheet("color: #8f9299; font-size: 12px;")
        layout.addWidget(self._subtitle)

    def set_card(self, title: str, subtitle: str = "") -> None:
        self._title_text = title
        self._subtitle_text = subtitle
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        self._draw_placeholder()

    def set_image(self, image: QImage) -> None:
        self._image = image
        pixmap = QPixmap.fromImage(image).scaled(
            self._cover_size, self._cover_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_label.setPixmap(pixmap)

    def set_cover_data(self, data: bytes) -> None:
        image = QImage()
        if image.loadFromData(data):
            self.set_image(image)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _draw_placeholder(self) -> None:
        pixmap = QPixmap(self._cover_size, self._cover_size)
        pixmap.fill(QColor("#2a2a30"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#62626e"))
        painter.setFont(QFont("Segoe UI Symbol", 42))
        painter.drawText(
            QRectF(0, 0, self._cover_size, self._cover_size),
            Qt.AlignmentFlag.AlignCenter,
            "♪",
        )
        painter.end()
        self._cover_label.setPixmap(pixmap)
