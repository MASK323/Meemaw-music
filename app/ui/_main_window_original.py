from __future__ import annotations

import json
import os
import threading
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPoint,
    QRect,
    QPropertyAnimation,
    QRectF,
    QSettings,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRegion,
)
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.core.images import ImageLoader
from app.core.kugou import KugouClient
from app.core.library import LibraryScanner
from app.core.models import Song
from app.core import netease
from app.core.player import PlayerManager
from app.core.tasks import TaskRunner
from app.ui.icons import IconButton
from app.ui.pages import (
    ChartsPage,
    DiscoverPage,
    FavoritesPage,
    KugouPage,
    LibraryPage,
    NowPlayingPage,
    RankDetailPage,
    SearchPage,
    SettingsPage,
)
from app.ui.splash import SplashOverlay
from app.ui.tray_player import DesktopLyricsWindow, TrayPlayerPopup
from app.ui.widgets import CommentsPanel, LyricsPanel, PlayerBar, QueuePanel


class WindowDragBar(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._window = window
        self._drag_offset = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self._window.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and not self._window.isMaximized():
            self._window.move(
                event.globalPosition().toPoint() - self._drag_offset
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._window._toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class PlayerTransitionOverlay(QWidget):
    """Full-window player transition that grows out of the bottom player bar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._background = None
        self._player = None
        self._bg_blur = None
        self._player_blur = None
        self._entry_pixmap = None
        self._progress = 0.0
        self._blur = 0.0
        self._fade = 1.0
        self._entry_rect = QRectF()
        self._live_page = None
        self._live_top_bar = None
        self._live_entry_widget = None
        self._live_cache = QPixmap()
        self._live_entry_cache = QPixmap()
        self._live_cache_elapsed = QElapsedTimer()
        self._live_cache_elapsed.start()
        self._live_cache_ready = False
        self._live_cache_refresh_ms = 33
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background: transparent; border: none;")
        self.hide()

    def set_content(
        self,
        background,
        player,
        bg_blur=None,
        player_blur=None,
        entry_rect=None,
        entry_pixmap=None,
    ) -> None:
        self._background = background
        self._player = player
        self._bg_blur = bg_blur
        self._player_blur = player_blur
        self._entry_pixmap = entry_pixmap
        self._entry_rect = QRectF(entry_rect) if entry_rect is not None else QRectF()
        self._progress = 0.0
        self._blur = 0.0
        self._fade = 1.0
        self._invalidate_live_cache()
        self.update()

    def set_player_pixmaps(self, player, player_blur=None) -> None:
        self._player = player
        self._player_blur = player_blur
        self.update()

    def set_live_widgets(self, page, top_bar=None, entry_widget=None) -> None:
        """Render the real player page live instead of a static snapshot."""
        self._live_page = page
        self._live_top_bar = top_bar
        self._live_entry_widget = entry_widget
        self._invalidate_live_cache()
        self.update()

    def _invalidate_live_cache(self) -> None:
        self._live_cache_ready = False
        self._live_cache_elapsed.restart()
        self._live_cache = QPixmap()
        self._live_entry_cache = QPixmap()

    def set_progress(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._progress) > 0.0005:
            self._progress = value
            self.update()

    def set_blur(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._blur) > 0.005:
            self._blur = value
            self.update()

    def set_fade(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._fade) > 0.005:
            self._fade = value
            self.update()

    def _draw_player_snapshot(
        self,
        painter,
        pixmap,
        top,
        target_height,
        source_y,
        source_h,
        opacity,
    ) -> None:
        width = float(self.width())
        if target_height <= 0.5 or opacity <= 0.005:
            return
        source_rect = QRectF(
            0.0,
            max(0.0, source_y),
            float(pixmap.width()),
            max(1.0, min(float(pixmap.height()), source_h)),
        )
        painter.setOpacity(max(0.0, min(1.0, opacity * self._fade)))
        painter.drawPixmap(
            QRectF(0.0, top, width, target_height),
            pixmap,
            source_rect,
        )
        painter.setOpacity(1.0)

    def _draw_player(self, painter) -> None:
        width = float(self.width())
        height = float(self.height())
        if self._live_page is not None and self._live_page.isVisible():
            player_width = width
            player_height = height
        elif self._live_cache_ready and not self._live_cache.isNull():
            # While the player page is hidden under the overlay, keep drawing
            # the last live frame so the prep work never shows through.
            player_width = width
            player_height = height
        elif self._player is not None and not self._player.isNull():
            player_width = float(self._player.width())
            player_height = float(self._player.height())
        else:
            return
        entry = self._entry_rect
        if entry.isNull() or entry.height() <= 0.0 or entry.width() <= 0.0:
            entry = QRectF(0.0, height * 0.86, width, height * 0.08)

        start_y = max(0.0, entry.y())
        start_bottom = min(height, entry.y() + entry.height())
        target_y = start_y * (1.0 - self._progress)
        target_bottom = start_bottom + (height - start_bottom) * self._progress
        target_height = target_bottom - target_y
        if target_height <= 0.5:
            return
        # Keep the bottom anchored while revealing the page upward.  The
        # source stays aligned with the target so no content is scaled or
        # warped during the transition.
        source_height = min(player_height, target_height * (player_width / width))
        source_y = max(0.0, player_height - source_height)
        source_h = min(source_height, player_height - source_y)
        if self._live_page is not None and self._live_page.isVisible():
            self._render_live_player(
                painter, source_y, source_h, target_y, target_height
            )
            return
        if self._live_cache_ready and not self._live_cache.isNull():
            self._draw_player_snapshot(
                painter,
                self._live_cache,
                target_y,
                target_height,
                source_y,
                source_h,
                1.0,
            )
            return
        self._draw_player_snapshot(
            painter,
            self._player,
            target_y,
            target_height,
            source_y,
            source_h,
            1.0,
        )

    def _render_live_player(
        self, painter, source_y, source_h, target_y, target_height
    ) -> None:
        if (
            not self._live_cache_ready
            or self._live_cache_elapsed.elapsed() >= self._live_cache_refresh_ms
        ):
            self._refresh_live_cache()
        if self._live_cache_ready and not self._live_cache.isNull():
            self._draw_player_snapshot(
                painter,
                self._live_cache,
                target_y,
                target_height,
                source_y,
                source_h,
                1.0,
            )

    def refresh_entry_cache(self) -> None:
        """Re-render the bottom player bar so its record keeps spinning."""
        entry = self._live_entry_widget
        if entry is None or entry.width() <= 0 or entry.height() <= 0:
            return
        if self._live_entry_cache.size() != entry.size():
            self._live_entry_cache = QPixmap(entry.size())
        self._live_entry_cache.fill(Qt.GlobalColor.transparent)
        entry_painter = QPainter(self._live_entry_cache)
        entry_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        entry.render(
            entry_painter,
            QPoint(0, 0),
            QRegion(0, 0, entry.width(), entry.height()),
        )
        entry_painter.end()

    def _refresh_live_cache(self, force: bool = False) -> None:
        if (
            not force
            and self._live_cache_ready
            and self._live_cache_elapsed.elapsed() < self._live_cache_refresh_ms
        ):
            return
        page = self._live_page
        root = self.parentWidget()
        if page is None or root is None:
            return
        if self.size().isEmpty():
            return
        size = self.size()
        if self._live_cache.size() != size:
            self._live_cache = QPixmap(size)
        self._live_cache.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._live_cache)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        bar = self._live_top_bar
        if (
            bar is not None
            and bar.isVisible()
            and bar.width() > 0
            and bar.height() > 0
        ):
            bar.render(
                painter,
                bar.mapTo(root, QPoint(0, 0)),
                QRegion(0, 0, bar.width(), bar.height()),
            )
        if page.isVisible() and page.width() > 0 and page.height() > 0:
            page.render(
                painter,
                page.mapTo(root, QPoint(0, 0)),
                QRegion(0, 0, page.width(), page.height()),
            )
        painter.end()

        self.refresh_entry_cache()
        self._live_cache_elapsed.restart()
        self._live_cache_ready = True

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipRect(self.rect())
        if self._background is not None and not self._background.isNull():
            bg_source = QRectF(
                0.0, 0.0, self._background.width(), self._background.height()
            )
            painter.setOpacity(max(0.0, min(1.0, self._fade)))
            painter.drawPixmap(QRectF(self.rect()), self._background, bg_source)
        else:
            # Never expose the widgets underneath, even if no snapshot is
            # available yet for a frame.
            painter.fillRect(self.rect(), QColor("#211e1c"))
        self._draw_player(painter)
        if (
            self._blur > 0.005
            and self._bg_blur is not None
            and not self._bg_blur.isNull()
        ):
            blur_source = QRectF(
                0.0, 0.0, self._bg_blur.width(), self._bg_blur.height()
            )
            painter.setOpacity(max(0.0, min(1.0, self._blur * self._fade)))
            painter.drawPixmap(QRectF(self.rect()), self._bg_blur, blur_source)
            painter.setOpacity(1.0)
        if self._progress < 1.0:
            entry_opacity = max(0.0, min(1.0, (1.0 - self._progress) * self._fade))
            if entry_opacity > 0.005 and not self._entry_rect.isNull():
                entry_widget = self._live_entry_widget
                if (
                    entry_widget is not None
                    and entry_widget.width() > 0
                    and entry_widget.height() > 0
                ):
                    if (
                        self._live_entry_cache is not None
                        and not self._live_entry_cache.isNull()
                        and self._live_entry_cache.size() == entry_widget.size()
                    ):
                        painter.setOpacity(entry_opacity)
                        painter.drawPixmap(
                            self._entry_rect,
                            self._live_entry_cache,
                            QRectF(self._live_entry_cache.rect()),
                        )
                        painter.setOpacity(1.0)
                    else:
                        painter.save()
                        painter.setOpacity(entry_opacity)
                        entry_widget.render(
                            painter,
                            QPoint(
                                round(self._entry_rect.x()),
                                round(self._entry_rect.y()),
                            ),
                            QRegion(
                                QRect(
                                    0,
                                    0,
                                    entry_widget.width(),
                                    entry_widget.height(),
                                )
                            ),
                        )
                        painter.restore()
                elif self._entry_pixmap is not None and not self._entry_pixmap.isNull():
                    entry_source = QRectF(
                        0.0,
                        0.0,
                        self._entry_pixmap.width(),
                        self._entry_pixmap.height(),
                    )
                    painter.setOpacity(entry_opacity)
                    painter.drawPixmap(self._entry_rect, self._entry_pixmap, entry_source)
                    painter.setOpacity(1.0)
        painter.end()


class SplashExitOverlay(QWidget):
    """Fades the finished splash snapshot out to reveal the main page."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._snapshot = None
        self._progress = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent; border: none;")
        self.hide()

    def set_snapshot(self, pixmap) -> None:
        self._snapshot = pixmap
        self._progress = 0.0
        self.update()

    def set_progress(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._progress) > 0.0005:
            self._progress = value
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipRect(self.rect())
        if self._snapshot is None or self._snapshot.isNull():
            painter.end()
            return
        progress = self._progress
        opacity = max(0.0, 1.0 - progress)
        scale = 1.0 + 0.05 * progress
        lift = 16.0 * progress
        width = float(self.width())
        height = float(self.height())
        target_w = width * scale
        target_h = height * scale
        painter.setOpacity(opacity)
        painter.drawPixmap(
            QRectF(
                (width - target_w) / 2.0,
                (height - target_h) / 2.0 - lift,
                target_w,
                target_h,
            ),
            self._snapshot,
            QRectF(0.0, 0.0, self._snapshot.width(), self._snapshot.height()),
        )
        painter.end()


class RoundedTrayMenu(QMenu):
    """Frameless, translucent context menu with rounded corners."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("trayMenu")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(
            """
            QMenu#trayMenu {
                background: transparent;
                border: none;
                padding: 5px;
            }
            QMenu#trayMenu::item {
                background: transparent;
                border-radius: 8px;
                margin: 1px 4px;
                padding: 5px 14px 5px 10px;
                color: #e8e8ec;
                font-size: 13px;
            }
            QMenu#trayMenu::item:selected {
                background: #ec4141;
                color: #ffffff;
            }
            QMenu#trayMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.10);
                margin: 4px 8px;
                border: none;
            }
            """
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(47, 41, 37, 252))
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            16,
            16,
        )
        painter.end()
        super().paintEvent(event)


class RootWidget(QWidget):
    """Central root that always paints the app background explicitly."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#211e1c"))
        painter.end()
        super().paintEvent(event)


class MainWindow(QMainWindow):
    kugou_ready = Signal(str)
    kugou_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Meemaw music")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.resize(1180, 760)
        self.setMinimumSize(1024, 640)
        self._opened = False
        self._closing = False
        self._tray_exit = False
        self._tray: Optional[QSystemTrayIcon] = None
        self._player: Optional[PlayerManager] = None
        self._media_devices = None
        self._tray_player_ready = False
        self._deferred_started = False

        self.images = ImageLoader(self)
        self.tasks = TaskRunner(self)
        self.scanner = LibraryScanner(self)
        self.kugou = KugouClient()
        threading.Thread(
            target=self._start_kugou_background, daemon=True
        ).start()

        self.liked_keys: set[str] = set()
        self.liked_songs: List[Song] = []
        self._settings = QSettings("MeemawMusic", "MeemawMusic")
        self._load_likes()
        self.music_folder: str = self._settings.value("music_folder", "") or ""
        self.quality: str = str(self._settings.value("quality", "320") or "320")
        saved_volume = float(self._settings.value("volume", 0.5) or 0.5)
        self._saved_volume = max(0.0, min(1.0, saved_volume))
        self.output_device: str = str(
            self._settings.value("output_device", "") or ""
        )
        self.kugou.quality = self.quality

        self._task_callbacks: Dict[str, Callable] = {}
        self._task_retries: Dict[str, int] = {}
        self._history: List[int] = []
        self._history_pos = -1
        self._comments_song_key: Optional[str] = None
        self._comments_offset = 0
        self._comments_total = 0
        self._comments_has_more = False
        self._comments_loading_more = False
        self._page_animation: Optional[QTimer] = None
        self._page_finish: Optional[Callable] = None
        self._finishing = False
        self._pending_show: Optional[tuple] = None
        self._panel_fades: Dict[int, QVariantAnimation] = {}
        self._splash_exit_overlay: Optional[SplashExitOverlay] = None
        self._splash_exit_animation: Optional[QVariantAnimation] = None

        self._build_ui()
        self._splash = SplashOverlay(self.root_widget)
        self._splash.finished.connect(self._on_splash_finished)
        self._splash.exit_snapshot.connect(self._on_splash_exit_snapshot)
        self._connect_signals()
        self._setup_tray()

        self._show_page(0)
        QTimer.singleShot(0, self.discover_page.load)
        QTimer.singleShot(420, self.charts_page.load)
        QTimer.singleShot(900, self.kugou_page.load)
        QTimer.singleShot(220, self._deferred_init)
        if self.music_folder:
            QTimer.singleShot(900, lambda: self.library_page.start_scan(self.music_folder))

    @property
    def player(self) -> PlayerManager:
        if self._player is None:
            self._ensure_player()
        return self._player

    def _ensure_player(self) -> None:
        if self._player is not None:
            return
        player = PlayerManager(self)
        player.url_resolver = self.kugou.resolve_song_url
        player.set_volume(self._saved_volume)
        if self.output_device:
            player.set_output_device_by_id(self.output_device)
        self._player = player
        self._connect_player_signals()

    def _ensure_media_devices(self):
        if self._media_devices is None:
            self._media_devices = QMediaDevices(self)
            self._media_devices.audioOutputsChanged.connect(
                self._on_output_devices_changed
            )
        return self._media_devices

    def _deferred_init(self) -> None:
        if self._closing or self._deferred_started:
            return
        self._deferred_started = True
        self._ensure_player()
        self._ensure_media_devices()
        self._setup_tray_player()
        self.player_bar.set_volume(self.player.volume())
        self.player_bar.set_play_mode(self.player.play_mode)
        self.now_playing_page.set_volume(self.player.volume())
        self.now_playing_page.set_play_mode(self.player.play_mode)
        self.settings_page.set_quality(self.quality)
        self.settings_page.refresh_output_devices(self.output_device)
        self.settings_page.set_output_device(self.output_device)
        self.now_playing_page.set_quality(self.quality)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._opened:
            self._opened = True
            self._play_open_animation()
            if getattr(self, "_splash", None) is not None:
                self._splash.start()

    def _on_splash_finished(self) -> None:
        self._splash = None

    def _on_splash_exit_snapshot(self, snapshot) -> None:
        if snapshot is None or snapshot.isNull() or self.root_widget is None:
            return
        overlay = SplashExitOverlay(self.root_widget)
        overlay.setGeometry(self.root_widget.rect())
        overlay.set_snapshot(snapshot)
        overlay.show()
        overlay.raise_()
        overlay.repaint()
        QApplication.processEvents()

        animation = QVariantAnimation(self)
        animation.setDuration(620)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(overlay.set_progress)

        def _finish() -> None:
            overlay.hide()
            overlay.deleteLater()
            self._splash_exit_overlay = None
            self._splash_exit_animation = None

        animation.finished.connect(_finish)
        self._splash_exit_overlay = overlay
        self._splash_exit_animation = animation
        animation.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _play_open_animation(self) -> None:
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(320)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        assets_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
        )
        icon_path = os.path.join(assets_dir, "icons", "app_icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(assets_dir, "vinyl", "disc.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        menu = RoundedTrayMenu()
        main_action = menu.addAction("主页面")
        main_action.triggered.connect(self._show_from_tray)
        player_action = menu.addAction("播放器")
        player_action.triggered.connect(self._show_player_from_tray)
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit_from_tray)

        tray = QSystemTrayIcon(self)
        tray.setIcon(icon)
        tray.setToolTip("Meemaw music")
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray

    def _setup_tray_player(self) -> None:
        if self._tray_player_ready:
            return
        self.tray_player = TrayPlayerPopup(self)
        self.desktop_lyrics = DesktopLyricsWindow(self)
        self.tray_player.play_toggled.connect(lambda: self.player.toggle())
        self.tray_player.next_requested.connect(lambda: self.player.next())
        self.tray_player.prev_requested.connect(lambda: self.player.previous())
        self.tray_player.like_toggled.connect(self._on_bar_like)
        self.tray_player.seek_requested.connect(lambda pos: self.player.seek(pos))
        self.tray_player.menu_clicked.connect(self._on_tray_player_menu)

        self.player.song_changed.connect(self._on_tray_song_changed)
        self.player.state_changed.connect(self.tray_player.set_state)
        self.player.position_changed.connect(self.tray_player.set_position)
        self.player.duration_changed.connect(self.tray_player.set_duration)
        self.player.position_changed.connect(self.desktop_lyrics.set_position)
        self._tray_player_ready = True

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._show_page(0, record=False)

    def _show_player_from_tray(self) -> None:
        self._deferred_init()
        if self.tray_player.isVisible():
            self.tray_player.hide()
        else:
            song = self.player.current_song
            liked = song is not None and song.key in self.liked_keys
            self.tray_player.set_song(song, liked)
            self.tray_player.set_state(self.player.state)
            self.tray_player.show_near_tray(self._tray)
            self.tray_player.set_position(self.player.position)
            self.tray_player.set_duration(self.player.duration)

    def _on_tray_player_menu(self, key: str) -> None:
        self._deferred_init()
        if key == "shuffle":
            modes = ["order", "list", "one", "shuffle"]
            current = self.player.play_mode if self.player.play_mode in modes else "order"
            next_mode = modes[(modes.index(current) + 1) % len(modes)]
            self._on_play_mode_changed(next_mode)
            self.tray_player.hide()
        elif key == "full":
            self.tray_player.hide()
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self._show_page(self._stack.indexOf(self.now_playing_page), record=False)
        elif key == "desktop_music":
            self.tray_player.hide()
            self.showNormal()
            self.raise_()
            self.activateWindow()
        elif key == "desktop_lyric":
            if self.desktop_lyrics.isVisible():
                self.desktop_lyrics.hide()
                self.tray_player.set_desktop_lyric_checked(False)
            else:
                song = self.player.current_song
                self.desktop_lyrics.set_song(song)
                self.desktop_lyrics.set_position(self.player.position)
                screen = self.screen()
                geometry = screen.availableGeometry() if screen is not None else self.frameGeometry()
                self.desktop_lyrics.move(
                    geometry.right() - self.desktop_lyrics.width() - 60,
                    geometry.bottom() - self.desktop_lyrics.height() - 90,
                )
                self.desktop_lyrics.show()
                self.tray_player.set_desktop_lyric_checked(True)
        elif key == "settings":
            self.tray_player.hide()
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self._show_page(self._stack.indexOf(self.settings_page), record=False)
        elif key == "exit":
            self.tray_player.hide()
            self._quit_from_tray()

    def _on_tray_song_changed(self, song: Optional[Song]) -> None:
        liked = song is not None and song.key in self.liked_keys
        self.tray_player.set_song(song, liked)
        self.desktop_lyrics.set_song(song)
        if self._tray is not None:
            self._tray.setToolTip(song.title if song is not None else "Meemaw music")

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _quit_from_tray(self) -> None:
        self._tray_exit = True
        self.close()

    def _start_kugou_background(self) -> None:
        try:
            self.kugou.start()
        except Exception as exc:
            if not self._closing:
                self.kugou_error.emit(str(exc))
            return
        if not self._closing:
            self.kugou_ready.emit("")

    def _build_ui(self) -> None:
        root = RootWidget()
        root.setObjectName("root")
        root.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCentralWidget(root)
        self.root_widget = root
        root_layout = QVBoxLayout(root)
        self.root_layout = root_layout
        root_layout.setContentsMargins(10, 0, 10, 10)
        root_layout.setSpacing(8)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        self._sidebar_widget = QWidget()
        self._sidebar_widget.setObjectName("sidebar")
        self._sidebar_widget.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(self._sidebar_widget)
        sidebar_layout.setContentsMargins(0, 16, 0, 12)
        sidebar_layout.setSpacing(6)

        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(16, 0, 12, 0)
        logo_row.setSpacing(8)
        assets_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
        )
        app_icon_path = os.path.join(assets_dir, "icons", "app_icon.png")
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(assets_dir, "icons", "app_icon.ico")
        logo_icon = IconButton("play", size=34, image=app_icon_path)
        logo_icon.setToolTip("Meemaw music")
        logo_icon.clicked.connect(lambda: self._show_page(0))
        logo_row.addWidget(logo_icon)
        app_title = QLabel("Meemaw music")
        app_title.setObjectName("appTitle")
        logo_row.addWidget(app_title)
        logo_row.addStretch(1)
        sidebar_layout.addLayout(logo_row)
        sidebar_layout.addSpacing(10)

        self._sidebar = QListWidget()
        self._sidebar.setObjectName("sidebarList")
        self._sidebar.addItems(
            [
                "精选",
                "排行榜",
                "我喜欢的音乐",
                "本地音乐",
                "设置",
            ]
        )
        sidebar_layout.addWidget(self._sidebar, 1)

        content_row.addWidget(self._sidebar_widget)

        right_panel = QWidget()
        self._right_panel = right_panel
        right_col = QVBoxLayout(right_panel)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(0)

        top_bar = WindowDragBar(self)
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(56)
        self.top_bar = top_bar
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 6, 8, 6)
        top_layout.setSpacing(8)

        self._collapse_btn = IconButton("collapse", size=30)
        self._collapse_btn.set_icon_color(QColor("#ffffff"))
        self._collapse_btn.setToolTip("收起播放器")
        self._collapse_btn.clicked.connect(self._exit_player_mode)
        self._collapse_btn.hide()
        top_layout.addWidget(self._collapse_btn)

        self._back = IconButton("back", size=30)
        self._back.set_icon_color(QColor("#c9ccd1"))
        self._back.setToolTip("后退")
        self._back.clicked.connect(self._go_back)
        self._forward = IconButton("forward", size=30)
        self._forward.set_icon_color(QColor("#c9ccd1"))
        self._forward.setToolTip("前进")
        self._forward.clicked.connect(self._go_forward)
        top_layout.addWidget(self._back)
        top_layout.addWidget(self._forward)
        top_layout.addSpacing(4)

        self._search_icon = IconButton("search", size=24)
        self._search_icon.set_icon_color(QColor("#8f9299"))
        self._search_icon.setToolTip("搜索")
        self._search_icon.clicked.connect(self._on_search)
        top_layout.addWidget(self._search_icon)

        self._search = QLineEdit()
        self._search.setObjectName("searchEdit")
        self._search.setPlaceholderText("搜索歌曲、歌手、专辑")
        self._search.setFixedSize(420, 46)
        self._search.returnPressed.connect(self._on_search)
        top_layout.addWidget(self._search)

        top_layout.addStretch(1)

        self.user_chip = QPushButton("账号登录")
        self.user_chip.setObjectName("userChip")
        self.user_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.user_chip.clicked.connect(lambda: self._show_page(5))
        top_layout.addWidget(self.user_chip)
        top_layout.addSpacing(10)

        self._min_btn = IconButton("minimize", size=30)
        self._min_btn.set_icon_color(QColor("#c9ccd1"))
        self._min_btn.setToolTip("最小化")
        self._min_btn.clicked.connect(self.showMinimized)
        top_layout.addWidget(self._min_btn)

        self._window_btn = IconButton("restore", size=30)
        self._window_btn.set_icon_color(QColor("#c9ccd1"))
        self._window_btn.setToolTip("窗口化")
        self._window_btn.clicked.connect(self.showNormal)
        top_layout.addWidget(self._window_btn)

        self._fullscreen_btn = IconButton("fullscreen", size=30)
        self._fullscreen_btn.set_icon_color(QColor("#c9ccd1"))
        self._fullscreen_btn.setToolTip("全屏")
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        top_layout.addWidget(self._fullscreen_btn)

        self._close_btn = IconButton("close", size=30)
        self._close_btn.set_icon_color(QColor("#c9ccd1"))
        self._close_btn.setToolTip("关闭到托盘")
        self._close_btn.clicked.connect(self.close)
        top_layout.addWidget(self._close_btn)

        right_col.addWidget(top_bar)

        self._stack = QStackedWidget()
        self.discover_page = DiscoverPage(self)
        self.charts_page = ChartsPage(self)
        self.search_page = SearchPage(self)
        self.favorites_page = FavoritesPage(self)
        self.library_page = LibraryPage(self)
        self.kugou_page = KugouPage(self)
        self.rank_detail_page = RankDetailPage(self)
        self.now_playing_page = NowPlayingPage(self)
        self.settings_page = SettingsPage(self)
        for page in (
            self.discover_page,
            self.charts_page,
            self.search_page,
            self.favorites_page,
            self.library_page,
            self.kugou_page,
            self.rank_detail_page,
            self.now_playing_page,
            self.settings_page,
        ):
            self._stack.addWidget(page)
        right_col.addWidget(self._stack, 1)
        self._player_overlay = PlayerTransitionOverlay(root)

        content_row.addWidget(right_panel, 1)

        self.queue_panel = QueuePanel()
        self.queue_panel.hide()
        content_row.addWidget(self.queue_panel)

        self.lyrics_panel = LyricsPanel()
        self.lyrics_panel.hide()
        content_row.addWidget(self.lyrics_panel)

        self.comments_panel = CommentsPanel()
        self.comments_panel.hide()
        content_row.addWidget(self.comments_panel)
        root_layout.addLayout(content_row, 1)

        self.player_bar = PlayerBar(self.images)
        root_layout.addWidget(self.player_bar)

    def _connect_signals(self) -> None:
        self._connect_static_signals()

    def _connect_static_signals(self) -> None:
        self.tasks.done.connect(self._on_task_done)
        self.tasks.failed.connect(self._on_task_failed)
        self.kugou_ready.connect(self._on_kugou_ready)
        self.kugou_error.connect(self.show_toast)
        self.scanner.finished.connect(self._on_scan_finished)
        self.scanner.failed.connect(self._on_scan_failed)
        self.scanner.progress.connect(self._on_scan_progress)

        self._sidebar.currentRowChanged.connect(self._on_sidebar_changed)

        self.kugou_page.login_changed.connect(self._on_kugou_login_changed)
        self.settings_page.quality_changed.connect(self._on_quality_changed)
        self.settings_page.output_device_changed.connect(
            self._on_output_device_changed
        )
        self.now_playing_page.quality_changed.connect(self._on_quality_changed)

        self.player_bar.clicked.connect(self._open_now_playing)
        self.player_bar.play_mode_changed.connect(self._on_play_mode_changed)
        self.player_bar.play_toggled.connect(lambda: self.player.toggle())
        self.player_bar.next_requested.connect(lambda: self.player.next())
        self.player_bar.prev_requested.connect(lambda: self.player.previous())
        self.player_bar.queue_toggled.connect(self._toggle_queue)
        self.player_bar.like_toggled.connect(self._on_bar_like)
        self.player_bar.comment_toggled.connect(self._toggle_comments)
        self.player_bar.volume_changed.connect(self._on_volume_changed)
        self.player_bar.seek_requested.connect(lambda pos: self.player.seek(pos))
        self.player_bar.lyric_toggled.connect(self._toggle_lyrics)
        self.lyrics_panel.seek_requested.connect(lambda pos: self.player.seek(pos))
        self.comments_panel.load_more_requested.connect(self._load_more_comments)

        self.now_playing_page.play_mode_changed.connect(self._on_play_mode_changed)
        self.now_playing_page.play_toggled.connect(lambda: self.player.toggle())
        self.now_playing_page.next_requested.connect(lambda: self.player.next())
        self.now_playing_page.prev_requested.connect(lambda: self.player.previous())
        self.now_playing_page.queue_toggled.connect(self._toggle_queue)
        self.now_playing_page.lyric_toggled.connect(self._toggle_lyrics)
        self.now_playing_page.comment_toggled.connect(self._toggle_comments)
        self.now_playing_page.like_toggled.connect(self._on_bar_like)
        self.now_playing_page.volume_changed.connect(self._on_volume_changed)
        self.now_playing_page.seek_requested.connect(
            lambda pos: self.player.seek(pos)
        )

        self.queue_panel.play_at.connect(self._on_queue_play)
        self.queue_panel.remove_at.connect(self._on_queue_remove)

    def _connect_player_signals(self) -> None:
        self.player.song_changed.connect(self._on_song_changed)
        self.player.state_changed.connect(self.player_bar.set_state)
        self.player.state_changed.connect(self.now_playing_page.set_state)
        self.player.position_changed.connect(self.player_bar.set_position)
        self.player.position_changed.connect(self.lyrics_panel.set_position)
        self.player.position_changed.connect(self.now_playing_page.set_position)
        self.player.duration_changed.connect(self.player_bar.set_duration)
        self.player.duration_changed.connect(self.now_playing_page.set_duration)
        self.player.queue_changed.connect(self._on_queue_changed)
        self.player.play_failed.connect(self.show_toast)
        self.player.loading_changed.connect(self._on_player_loading)

    def run_task(self, token: str, fn: Callable, callback: Callable, *args, **kwargs) -> None:
        self._task_callbacks[token] = callback
        retries = self._task_retries.get(token, 0)
        if self.tasks.run(token, fn, *args, **kwargs):
            self._task_retries[token] = 0
            return
        if retries >= 6:
            self._task_retries[token] = 0
            self._task_callbacks.pop(token, None)
            self._on_task_failed(token, "任务繁忙，请稍后重试")
            return
        self._task_retries[token] = retries + 1
        QTimer.singleShot(
            150,
            lambda: self.run_task(token, fn, callback, *args, **kwargs),
        )

    def _on_task_done(self, token: str, result) -> None:
        callback = self._task_callbacks.pop(token, None)
        if callback is not None:
            callback(result)

    def _on_task_failed(self, token: str, message: str) -> None:
        self._task_callbacks.pop(token, None)
        if token.startswith("discover_kugou:"):
            self.discover_page._refresh.setEnabled(True)
        if token.startswith("lyrics:"):
            return
        if token.startswith("comments:"):
            self.comments_panel.set_empty("评论暂时加载失败，请稍后重试")
            return
        if token.startswith("comments_more:"):
            self._comments_loading_more = False
            self.comments_panel.set_more_error("加载失败，继续下拉可重试")
            return
        if token.startswith("likes:"):
            return
        self.kugou_page.notify_task_failed(token)
        self.show_toast(f"网络请求失败：{message}")

    def start_scan(self, path: str) -> None:
        self.music_folder = path
        self._settings.setValue("music_folder", path)
        self.scanner.scan_in_thread(path)

    def _on_scan_progress(self, message: str) -> None:
        self.library_page._count.setText(message)

    def _on_scan_finished(self, songs: List[Song]) -> None:
        self.library_page.set_scan_result(songs)

    def _on_scan_failed(self, message: str) -> None:
        self.library_page.set_scan_error(message)

    def play_song(self, song: Song) -> None:
        self.player.play_song(song)

    def play_songs(self, songs: List[Song], index: int = 0) -> None:
        self.player.play_queue(songs, index)

    def toggle_like(self, song: Optional[Song]) -> None:
        if song is None:
            return
        key = song.key
        if key in self.liked_keys:
            self.liked_keys.discard(key)
            self.liked_songs = [s for s in self.liked_songs if s.key != key]
        else:
            self.liked_keys.add(key)
            self.liked_songs.append(song)

        for page in (
            self.charts_page,
            self.search_page,
            self.library_page,
            self.favorites_page,
            self.rank_detail_page,
        ):
            if hasattr(page, "_table") and page._table.isVisible():
                page._table.set_liked_keys(self.liked_keys)
        self.favorites_page.refresh()
        if self.player.current_song is not None and self.player.current_song.key == key:
            liked = key in self.liked_keys
            self.player_bar.set_song(self.player.current_song, liked)
            self.now_playing_page.set_liked(liked)
            if hasattr(self, "tray_player"):
                self.tray_player.set_liked(liked)
        self._save_likes()

    def _load_likes(self) -> None:
        raw = self._settings.value("liked_songs", "") or ""
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            data = []
        self.liked_keys.clear()
        self.liked_songs.clear()
        if not isinstance(data, list):
            return
        fields = set(Song.__dataclass_fields__)
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                song = Song(**{k: v for k, v in item.items() if k in fields})
            except (TypeError, ValueError):
                continue
            self.liked_songs.append(song)
            self.liked_keys.add(song.key)

    def _save_likes(self) -> None:
        data = [
            {
                "title": song.title,
                "artist": song.artist,
                "album": song.album,
                "duration": song.duration,
                "url": song.url,
                "local_path": song.local_path,
                "cover_url": song.cover_url,
                "track_id": song.track_id,
                "source": song.source,
                "fallback_url": song.fallback_url,
                "kugou_hash": song.kugou_hash,
            }
            for song in self.liked_songs
        ]
        self._settings.setValue(
            "liked_songs", json.dumps(data, ensure_ascii=False)
        )

    def show_toast(self, message: str) -> None:
        self.player_bar.show_toast(message)

    def _on_sidebar_changed(self, row: int) -> None:
        actions = {
            0: ("page", 0),
            1: ("page", 1),
            2: ("page", 3),
            3: ("page", 4),
            4: ("page", 8),
        }
        action = actions.get(row)
        if action is None:
            return
        kind, value = action
        if kind == "page":
            self._show_page(value)

    def _show_page(self, index: int, record: bool = True) -> None:
        # A transition is still tearing down/starting up (the animation
        # group is alive or its finish callback is running). Queue the
        # request so a click during that cleanup cannot cancel the new
        # transition and leave the player page without an animation.
        if self._page_animation is not None or self._finishing:
            self._pending_show = (index, bool(record))
            return
        previous_index = self._stack.currentIndex()
        if record:
            if self._history_pos >= 0 and self._history[self._history_pos] == index:
                pass
            else:
                del self._history[self._history_pos + 1 :]
                self._history.append(index)
                self._history_pos = len(self._history) - 1
        if 0 <= index < self._stack.count():
            self._animate_page_switch(index)
        self._sidebar.blockSignals(True)
        row_map = {0: 0, 1: 1, 3: 2, 4: 3, 8: 4}
        row = row_map.get(index, -1)
        self._sidebar.setCurrentRow(row)
        self._sidebar.blockSignals(False)
        if index == 3:
            self.favorites_page.refresh()
        self._update_nav()

    def _set_player_mode(self, active: bool) -> None:
        self._sidebar_widget.setVisible(not active)
        self.player_bar.setVisible(not active)
        self._collapse_btn.setVisible(active)
        self._back.setVisible(not active)
        self._forward.setVisible(not active)
        self._search_icon.setVisible(not active)
        self._search.setVisible(not active)
        self.user_chip.setVisible(not active)
        if active:
            self.queue_panel.hide()
            self.lyrics_panel.hide()
            self.comments_panel.hide()
            self.root_layout.setContentsMargins(0, 0, 0, 0)
            self.root_layout.setSpacing(0)
            self.top_bar.setStyleSheet(
                "QWidget#topBar { background: #4a4a4a; border: none; }"
            )
        else:
            self.root_layout.setContentsMargins(10, 0, 10, 10)
            self.root_layout.setSpacing(8)
            self.top_bar.setStyleSheet("")

    def _set_transition_mode(self, page, active: bool) -> None:
        """Let animated widgets advance state without scheduling repaints."""
        disc = getattr(page, "_art", None)
        if disc is not None and hasattr(disc, "set_transition_mode"):
            disc.set_transition_mode(active)
        lyrics = getattr(page, "_lyrics", None)
        if lyrics is not None and hasattr(lyrics, "set_transition_mode"):
            lyrics.set_transition_mode(active)

    def _blur_pixmap(self, pixmap, radius: float):
        """Return a soft blurred copy, rendered at half size for speed."""
        if pixmap is None or pixmap.isNull():
            return pixmap
        scene = QGraphicsScene(self)
        item = QGraphicsPixmapItem(pixmap)
        effect = QGraphicsBlurEffect()
        effect.setBlurRadius(max(0.0, float(radius) * 0.5))
        item.setGraphicsEffect(effect)
        scene.addItem(item)
        scene.setSceneRect(QRectF(0.0, 0.0, pixmap.width(), pixmap.height()))
        half_w = max(1, pixmap.width() // 2)
        half_h = max(1, pixmap.height() // 2)
        image = QImage(half_w, half_h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        scene.render(painter)
        painter.end()
        blurred = QPixmap.fromImage(image)
        return blurred.scaled(
            pixmap.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _compose_window_snapshot(self) -> QPixmap:
        """Render the current visible widgets into one full-window pixmap.

        Child widget grab() is unreliable on some Windows/high-DPI setups and
        returns blank frames, so render the root widget directly instead.
        """
        sidebar = getattr(self, "_sidebar", None)
        if sidebar is not None:
            sidebar.repaint()
        right_panel = getattr(self, "_right_panel", None)
        if right_panel is not None:
            right_panel.repaint()
        pixmap = QPixmap(self.size())
        pixmap.fill(QColor("#211e1c"))
        overlay = getattr(self, "_player_overlay", None)
        splash = getattr(self, "_splash", None)
        splash_exit = getattr(self, "_splash_exit_overlay", None)
        hidden = []
        for widget in (overlay, splash, splash_exit):
            if widget is not None and widget.isVisible():
                widget.hide()
                hidden.append(widget)
        self.root_widget.render(pixmap)
        for widget in hidden:
            widget.show()
        self.root_widget.repaint()
        return pixmap

    @staticmethod
    def _render_widget_pixmap(widget: QWidget) -> QPixmap:
        """Render a child widget to a logical-size pixmap using render()."""
        pixmap = QPixmap(widget.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        widget.render(pixmap)
        return pixmap

    def _animate_page_switch(self, index: int) -> None:
        old_finish = self._page_finish
        old_animation = self._page_animation
        self._page_finish = None
        self._page_animation = None
        if old_animation is not None:
            old_animation.stop()
        current = self._stack.currentWidget()
        if old_finish is not None:
            old_finish()
            current = self._stack.currentWidget()
        page = self._stack.widget(index)
        if page is None or page is current:
            return

        now_playing_index = self._stack.indexOf(self.now_playing_page)
        if page is self.now_playing_page and current is not self.now_playing_page:
            self._animate_player_enter(index, current)
        elif current is self.now_playing_page and page is not self.now_playing_page:
            self._animate_player_exit(index, page)
        else:
            self._animate_regular_switch(index, current, page)

    def _on_page_switch_finished(self) -> None:
        finish = self._page_finish
        self._page_finish = None
        if finish is not None:
            self._finishing = True
            try:
                finish()
            finally:
                self._finishing = False
                pending = self._pending_show
                self._pending_show = None
                if pending is not None:
                    self._show_page(pending[0], pending[1])

    @staticmethod
    def _ease_in_out_quad(t: float) -> float:
        t = max(0.0, min(1.0, t))
        if t < 0.5:
            return 2.0 * t * t
        return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0

    @staticmethod
    def _ease_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1.0 - (1.0 - t) ** 3

    def _start_transition(
        self,
        duration_ms: int,
        ease: Callable[[float], float],
        on_value: Callable[[float], None],
        on_finish: Callable[[], None],
    ) -> QTimer:
        """Drive a transition with a wall-clock timer.

        Qt's shared animation clock can start a new animation several hundred
        milliseconds ahead when one was just torn down, which makes the player
        transition look like it skipped to the middle and then sped up.  A
        QElapsedTimer-based driver keeps progress proportional to real time,
        with a per-frame cap so a slow frame never makes the motion jump.
        """
        timer = QTimer(self)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.setInterval(16)
        clock = QElapsedTimer()
        clock.start()
        finished = False
        last_t = 0.0
        # A slow frame (page snapshot, blur, resize) can stall the event loop.
        # Wall-clock progress then catches up in one tick and the transition
        # visibly speeds up.  Cap the per-frame catch-up so the motion stays
        # smooth even when a frame is late.
        max_step = min(1.0, (16.0 * 2.5) / float(max(1, duration_ms)))

        def _tick() -> None:
            nonlocal finished, last_t
            if finished:
                return
            raw_t = min(1.0, clock.elapsed() / float(max(1, duration_ms)))
            t = min(raw_t, last_t + max_step)
            last_t = t
            on_value(ease(t))
            if t >= 1.0:
                finished = True
                timer.stop()
                timer.deleteLater()
                on_finish()

        timer.timeout.connect(_tick)
        _tick()
        timer.start()
        return timer

    def _animate_regular_switch(self, index: int, current, page) -> None:
        self._stack.setCurrentIndex(index)
        if current is not None:
            current.setGraphicsEffect(None)
            current.move(0, 0)

        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)
        start_pos = page.pos()
        page.move(start_pos.x(), start_pos.y() + 22)

        def _finish() -> None:
            self._page_animation = None
            self._page_finish = None
            page.setGraphicsEffect(None)
            page.move(0, 0)

        def _step(p: float) -> None:
            p = max(0.0, min(1.0, float(p)))
            effect.setOpacity(p)
            page.move(start_pos.x(), start_pos.y() + 22.0 * (1.0 - p))

        self._page_finish = _finish
        self._page_animation = self._start_transition(
            280, self._ease_out_cubic, _step, self._on_page_switch_finished
        )

    def _player_entry_rect(self) -> QRectF:
        origin = self.player_bar.mapTo(self, QPoint(0, 0))
        return QRectF(
            origin.x(),
            origin.y(),
            self.player_bar.width(),
            self.player_bar.height(),
        )

    def _animate_player_enter(self, index: int, current) -> None:
        page = self.now_playing_page
        overlay = self._player_overlay
        current_index = self._stack.indexOf(current)
        if current is not None:
            current.setGraphicsEffect(None)
            current.setGeometry(self._stack.rect())
            current.move(0, 0)
            current.show()
            current.raise_()

        # Render the main page into a snapshot while it is fully visible,
        # then cover the whole window before any real widget is switched.
        self._set_player_mode(False)
        self._stack.setCurrentIndex(current_index)
        self.root_layout.activate()
        if current is not None:
            current.setGraphicsEffect(None)
            current.setGeometry(self._stack.rect())
            current.move(0, 0)
            current.show()
            current.raise_()
            current.repaint()
        background = self._compose_window_snapshot()
        background_blur = self._blur_pixmap(background, 18.0)
        entry_rect = self._player_entry_rect()
        bar_pixmap = self._render_widget_pixmap(self.player_bar)

        overlay.set_content(
            background,
            None,
            bg_blur=background_blur,
            entry_rect=entry_rect,
            entry_pixmap=bar_pixmap,
        )
        overlay.setGeometry(overlay.parentWidget().rect())
        overlay.set_progress(0.0)
        overlay.set_blur(0.8)
        overlay.set_fade(1.0)
        overlay.show()
        overlay.raise_()
        overlay.repaint()
        QApplication.processEvents()

        # Switch to the real player page underneath the opaque overlay. The
        # overlay renders this live page on every frame, so the record keeps
        # spinning and the lyrics keep scrolling while the page rises.
        self._set_player_mode(True)
        self._stack.setCurrentIndex(index)
        page.setGraphicsEffect(None)
        page.setGeometry(self._stack.rect())
        page.move(0, 0)
        page.show()
        page.raise_()
        if current is not None:
            current.setGraphicsEffect(None)
            current.hide()
        self.root_layout.activate()
        page.repaint()
        QApplication.processEvents()
        overlay.set_live_widgets(page, self.top_bar, self.player_bar)
        overlay._refresh_live_cache()
        self._set_transition_mode(page, True)
        overlay.set_progress(0.0)
        overlay.set_blur(0.8)
        overlay.set_fade(1.0)

        def _on_enter_progress(value) -> None:
            p = max(0.0, min(1.0, float(value)))
            overlay._refresh_live_cache()
            overlay.refresh_entry_cache()
            overlay.set_progress(p)
            overlay.set_blur(0.8 * (1.0 - p))

        def _end_enter() -> None:
            self._set_transition_mode(page, False)
            overlay.set_live_widgets(page, self.top_bar, self.player_bar)
            overlay._refresh_live_cache(force=True)
            overlay.refresh_entry_cache()
            overlay.set_progress(1.0)
            overlay.set_blur(0.0)
            overlay.set_fade(1.0)
            overlay.repaint()
            overlay.hide()
            overlay.set_live_widgets(None, None)
            QApplication.processEvents()
            self._page_animation = None
            self._page_finish = None

        self._page_finish = _end_enter
        self._page_animation = self._start_transition(
            860, self._ease_in_out_quad, _on_enter_progress, self._on_page_switch_finished
        )

    def _animate_player_exit(self, index: int, target) -> None:
        page = self.now_playing_page
        overlay = self._player_overlay
        self._set_player_mode(True)
        self._stack.setCurrentIndex(self._stack.indexOf(page))
        page.setGraphicsEffect(None)
        page.setGeometry(self._stack.rect())
        page.move(0, 0)
        page.show()
        page.raise_()
        self.root_layout.activate()
        page.repaint()
        QApplication.processEvents()

        # Cover the whole window with the live player page before the main
        # page is prepared underneath, so the switch is never visible.
        overlay.set_live_widgets(page, self.top_bar, self.player_bar)
        overlay.set_content(None, None)
        overlay.setGeometry(overlay.parentWidget().rect())
        overlay.set_progress(1.0)
        overlay.set_blur(0.0)
        overlay.set_fade(1.0)
        overlay.show()
        overlay.raise_()
        overlay.repaint()
        QApplication.processEvents()

        # Prepare the main page underneath the opaque overlay.
        self._set_player_mode(False)
        self._stack.setCurrentIndex(index)
        target.setGraphicsEffect(None)
        target.setGeometry(self._stack.rect())
        target.move(0, 0)
        target.show()
        target.raise_()
        self.root_layout.activate()
        target.repaint()
        QApplication.processEvents()
        # Select the destination row before the background snapshot is taken,
        # so the overlay shows the settled sidebar for the whole exit and the
        # red active item never pops in after the overlay is hidden.
        self._sidebar.blockSignals(True)
        row_map = {0: 0, 1: 1, 3: 2, 4: 3, 8: 4}
        self._sidebar.setCurrentRow(row_map.get(index, -1))
        self._sidebar.blockSignals(False)
        target.repaint()
        QApplication.processEvents()
        entry_rect = self._player_entry_rect()
        bar_pixmap = self._render_widget_pixmap(self.player_bar)

        main_pixmap = self._compose_window_snapshot()
        main_blur = self._blur_pixmap(main_pixmap, 18.0)

        # Bring the real player page back up under the overlay so the record
        # keeps rotating while the page shrinks down into the player bar.
        self._set_player_mode(True)
        self._stack.setCurrentIndex(self._stack.indexOf(page))
        page.setGraphicsEffect(None)
        page.setGeometry(self._stack.rect())
        page.move(0, 0)
        page.show()
        page.raise_()
        self.root_layout.activate()
        page.repaint()
        QApplication.processEvents()

        overlay.set_content(
            main_pixmap,
            None,
            bg_blur=main_blur,
            entry_rect=entry_rect,
            entry_pixmap=bar_pixmap,
        )
        overlay.set_live_widgets(page, self.top_bar, self.player_bar)
        overlay._refresh_live_cache()
        self._set_transition_mode(page, True)
        overlay.set_progress(1.0)
        overlay.set_blur(0.0)
        overlay.set_fade(1.0)

        def _on_exit_progress(value) -> None:
            p = max(0.0, min(1.0, float(value)))
            overlay._refresh_live_cache()
            overlay.refresh_entry_cache()
            overlay.set_progress(1.0 - p)
            overlay.set_blur(0.0)

        def _end_exit() -> None:
            self._set_transition_mode(page, False)
            self._set_player_mode(False)
            self._stack.setCurrentIndex(index)
            target.setGraphicsEffect(None)
            target.setGeometry(self._stack.rect())
            target.move(0, 0)
            target.show()
            target.raise_()
            self.root_layout.activate()
            target.repaint()
            self.top_bar.repaint()
            self.player_bar.repaint()
            self._sidebar_widget.repaint()
            QApplication.processEvents()
            # Finish on the already-composed main page snapshot plus a fresh
            # player bar.  This keeps the record angle continuous and avoids
            # an expensive full-window re-render right at the end.
            overlay.set_content(
                main_pixmap,
                None,
                entry_rect=entry_rect,
                entry_pixmap=bar_pixmap,
            )
            overlay.set_live_widgets(None, self.top_bar, self.player_bar)
            overlay.refresh_entry_cache()
            overlay.set_progress(0.0)
            overlay.set_blur(0.0)
            overlay.set_fade(1.0)
            overlay.repaint()
            overlay.hide()
            QApplication.processEvents()
            self._page_animation = None
            self._page_finish = None

        self._page_finish = _end_exit
        self._page_animation = self._start_transition(
            840, self._ease_in_out_quad, _on_exit_progress, self._on_page_switch_finished
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        overlay = getattr(self, "_player_overlay", None)
        if overlay is not None:
            overlay.setGeometry(overlay.parentWidget().rect())
        splash = getattr(self, "_splash", None)
        if splash is not None and self.root_widget is not None:
            splash.setGeometry(self.root_widget.rect())
        splash_exit = getattr(self, "_splash_exit_overlay", None)
        if splash_exit is not None and self.root_widget is not None:
            splash_exit.setGeometry(self.root_widget.rect())

    def _fade_in_panel(self, panel) -> None:
        old = self._panel_fades.pop(id(panel), None)
        if old is not None:
            old.stop()
        panel.setGraphicsEffect(None)
        panel.show()
        effect = QGraphicsOpacityEffect(panel)
        effect.setOpacity(0.0)
        panel.setGraphicsEffect(effect)
        animation = QVariantAnimation(self)
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_value(value) -> None:
            effect.setOpacity(max(0.0, min(1.0, float(value))))

        def _finish() -> None:
            self._panel_fades.pop(id(panel), None)
            panel.setGraphicsEffect(None)

        animation.valueChanged.connect(_on_value)
        animation.finished.connect(_finish)
        self._panel_fades[id(panel)] = animation
        animation.start()

    def _update_nav(self) -> None:
        self._back.setEnabled(self._history_pos > 0)
        self._forward.setEnabled(self._history_pos < len(self._history) - 1)
        self._back.set_icon_color(
            QColor("#c9ccd1") if self._back.isEnabled() else QColor("#555860")
        )
        self._forward.set_icon_color(
            QColor("#c9ccd1") if self._forward.isEnabled() else QColor("#555860")
        )

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _go_back(self) -> None:
        if self._history_pos > 0:
            self._history_pos -= 1
            self._show_page(self._history[self._history_pos], record=False)

    def _go_forward(self) -> None:
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            self._show_page(self._history[self._history_pos], record=False)

    def _on_search(self) -> None:
        term = self._search.text().strip()
        if not term:
            return
        self._show_page(2)
        self.search_page.start_search(term)

    def _on_song_changed(self, song: Optional[Song]) -> None:
        if song is None or not (song.title or "").strip():
            self.setWindowTitle("Meemaw music")
        else:
            self.setWindowTitle(str(song.title).strip())
        liked = song is not None and song.key in self.liked_keys
        self.player_bar.set_song(song, liked)
        self.lyrics_panel.set_song(song)
        self.comments_panel.set_song(song)
        self.now_playing_page.set_song(song, liked)
        self._load_lyrics(song)
        QTimer.singleShot(
            160,
            lambda s=song: self._load_comments(s)
            if self.player.current_song is s
            else None,
        )
        QTimer.singleShot(
            320,
            lambda s=song: self._load_like_count(s)
            if self.player.current_song is s
            else None,
        )
        if song is None and self._stack.currentWidget() is self.now_playing_page:
            if self._history_pos > 0:
                self._go_back()
            else:
                self._show_page(0)

    def _load_lyrics(self, song: Optional[Song]) -> None:
        if song is None or not song.kugou_hash:
            return
        current = song
        self.run_task(
            f"lyrics:{song.key}",
            self.kugou.fetch_lyrics,
            lambda lines: self._on_lyrics_loaded(current, lines),
            song.kugou_hash,
        )

    def _on_lyrics_loaded(self, song: Song, lines) -> None:
        if self.player.current_song is not song:
            return
        self.lyrics_panel.set_lyrics(lines)
        self.now_playing_page.set_lyrics(lines)
        self.tray_player.set_lyrics(lines)
        self.desktop_lyrics.set_lyrics(lines)

    def _load_comments(self, song: Optional[Song]) -> None:
        if song is None:
            self.comments_panel.set_song(None)
            return
        current = song
        self._comments_song_key = song.key
        self._comments_offset = 0
        self._comments_total = 0
        self._comments_has_more = False
        self._comments_loading_more = False
        self.comments_panel.set_loading()
        self.run_task(
            f"comments:{song.key}",
            netease.fetch_song_comments_page,
            lambda comments: self._on_comments_loaded(current, comments),
            song,
            0,
            100,
            True,
        )

    def _load_like_count(self, song: Optional[Song]) -> None:
        if song is None:
            return
        current = song
        self.run_task(
            f"likes:{song.key}",
            netease.fetch_song_like_count,
            lambda count: self._on_like_count_loaded(current, count),
            song,
        )

    def _on_like_count_loaded(self, song: Song, count) -> None:
        if self.player.current_song is not song:
            return
        count = max(0, int(count or 0))
        self.player_bar.set_like_count(count)
        self.now_playing_page.set_like_count(count)

    def _on_comments_loaded(self, song: Song, result) -> None:
        if self.player.current_song is not song:
            return
        comments, total, next_offset, has_more = result
        self._comments_total = max(0, int(total or 0))
        self._comments_has_more = bool(has_more)
        self._comments_offset = max(0, int(next_offset or 0))
        self._comments_loading_more = False
        self.comments_panel.set_comments(comments)
        self.comments_panel.set_has_more(self._comments_has_more)

    def _load_more_comments(self) -> None:
        song = self.player.current_song
        if (
            song is None
            or self._comments_song_key != song.key
            or not self._comments_has_more
            or self._comments_loading_more
        ):
            return
        self._comments_loading_more = True
        self.comments_panel.set_loading_more()
        current = song
        seen = {
            str(item.get("content") or "")[:120]
            for item in self.comments_panel.comments()
        }
        self.run_task(
            f"comments_more:{song.key}",
            netease.fetch_song_comments_page,
            lambda result: self._on_comments_more_loaded(current, result),
            song,
            self._comments_offset,
            60,
            False,
            seen,
        )

    def _on_comments_more_loaded(self, song: Song, result) -> None:
        if self.player.current_song is not song:
            return
        comments, total, next_offset, has_more = result
        self._comments_loading_more = False
        if not comments:
            self._comments_has_more = False
            self.comments_panel.set_has_more(False)
            return
        self._comments_total = max(0, int(total or 0))
        self._comments_has_more = bool(has_more)
        self._comments_offset = max(0, int(next_offset or 0))
        self.comments_panel.append_comments(comments)
        self.comments_panel.set_has_more(self._comments_has_more)

    def open_rank_detail(self, rank_id: str, item: Optional[Dict] = None) -> None:
        self.rank_detail_page.open_rank(rank_id, item)
        self._show_page(self._stack.indexOf(self.rank_detail_page))

    def _open_now_playing(self) -> None:
        if self.player.current_song is None:
            return
        self._show_page(self._stack.indexOf(self.now_playing_page))

    def _exit_player_mode(self) -> None:
        if self._stack.currentWidget() is not self.now_playing_page:
            return
        if self._history_pos > 0:
            self._go_back()
        else:
            self._show_page(0)

    def keyPressEvent(self, event) -> None:
        if (
            event.key() == Qt.Key.Key_Escape
            and self._stack.currentWidget() is self.now_playing_page
        ):
            self._exit_player_mode()
            return
        super().keyPressEvent(event)

    def _on_player_loading(self, message: str) -> None:
        self.player_bar.show_toast(message)

    def _on_kugou_login_changed(self) -> None:
        self.user_chip.setText(self.kugou.nickname if self.kugou.logged_in else "账号登录")
        self.settings_page.refresh_account()

    def _on_kugou_ready(self, _: str = "") -> None:
        self._on_kugou_login_changed()

    def _on_quality_changed(self, quality: str) -> None:
        if not quality or quality == self.quality:
            return
        self.quality = quality
        self._settings.setValue("quality", quality)
        self.kugou.quality = quality
        self.settings_page.set_quality(quality)
        self.now_playing_page.set_quality(quality)
        self.player.reload_current()
        self.show_toast(f"音质已切换：{self._quality_label(quality)}")

    def _on_output_device_changed(self, device_id: str) -> None:
        if not device_id:
            return
        self.output_device = device_id
        self._settings.setValue("output_device", device_id)
        self.player.set_output_device_by_id(device_id)
        self.show_toast("已切换输出设备")

    def _on_output_devices_changed(self) -> None:
        selected = str(self._settings.value("output_device", "") or "")
        self.settings_page.refresh_output_devices(selected)

    @staticmethod
    def _quality_label(quality: str) -> str:
        labels = {
            "128": "流畅 128kbps",
            "320": "高品质 320kbps",
            "flac": "无损 FLAC",
            "high": "Hi-Res",
        }
        return labels.get(quality, quality)

    def _on_queue_changed(self, songs: List[Song]) -> None:
        self.queue_panel.set_queue(songs, self.player.current_index)

    def _on_queue_play(self, index: int) -> None:
        songs = self.player.queue
        if songs:
            self.player.play_queue(songs, index)

    def _on_queue_remove(self, index: int) -> None:
        if index < 0:
            self.player.clear_queue()
        else:
            self.player.remove_at(index)

    def _toggle_queue(self) -> None:
        visible = not self.queue_panel.isVisible()
        if visible:
            self.lyrics_panel.hide()
            self.comments_panel.hide()
            self._fade_in_panel(self.queue_panel)
        else:
            self.queue_panel.hide()

    def _toggle_lyrics(self) -> None:
        visible = not self.lyrics_panel.isVisible()
        if visible:
            self.queue_panel.hide()
            self.comments_panel.hide()
            self._fade_in_panel(self.lyrics_panel)
        else:
            self.lyrics_panel.hide()

    def _toggle_comments(self) -> None:
        visible = not self.comments_panel.isVisible()
        if visible:
            self.queue_panel.hide()
            self.lyrics_panel.hide()
            self._fade_in_panel(self.comments_panel)
        else:
            self.comments_panel.hide()

    def _on_play_mode_changed(self, mode: str) -> None:
        self.player.set_play_mode(mode)
        self.player_bar.set_play_mode(mode)
        self.now_playing_page.set_play_mode(mode)

    def _on_bar_like(self) -> None:
        self.toggle_like(self.player.current_song)

    def _on_volume_changed(self, value: float) -> None:
        self.player.set_volume(value)
        self.player_bar.set_volume(value)
        self.now_playing_page.set_volume(value)
        self._settings.setValue("volume", float(value))

    def closeEvent(self, event) -> None:
        if self._tray is not None and not self._tray_exit:
            event.ignore()
            if getattr(self, "desktop_lyrics", None) is not None:
                self.desktop_lyrics.hide()
            if getattr(self, "tray_player", None) is not None:
                self.tray_player.set_desktop_lyric_checked(False)
            self.hide()
            return
        self._closing = True
        if self._player is not None:
            self._settings.setValue("volume", float(self.player.volume()))
        self._save_likes()
        if self._player is not None:
            self.player.shutdown()
        self.kugou.stop()
        netease.release_caches()
        self.kugou.release_caches()
        if self._tray is not None:
            self._tray.hide()
        if getattr(self, "tray_player", None) is not None:
            self.tray_player.hide()
        if getattr(self, "desktop_lyrics", None) is not None:
            self.desktop_lyrics.hide()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()
        QTimer.singleShot(800, lambda: os._exit(0))
