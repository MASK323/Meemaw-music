from __future__ import annotations

import base64
from datetime import datetime
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.downloader import download_rank_songs
from app.core.models import AlbumCard, BannerItem, LyricLine, Song
from app.core.netease import fetch_rank_detail, fetch_rank_list, match_rank_songs
from app.ui.icons import IconButton
from app.ui.widgets import CoverCard, LyricView, SeekSlider, SongTable, VinylDisc, VolumeControl


class ChartProgress(QObject):
    changed = Signal(str)


class SlimCombo(QComboBox):
    """Combo box with a slim painted chevron instead of the native arrow."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(
                QColor("#d9d2cc"),
                1.6,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        cx = self.width() - 12
        cy = self.height() // 2 + 1
        path = QPainterPath()
        path.moveTo(cx - 3.5, cy - 1.5)
        path.lineTo(cx, cy + 1.5)
        path.lineTo(cx + 3.5, cy - 1.5)
        painter.drawPath(path)


class QualityCombo(SlimCombo):
    pass


class SpeakerCombo(SlimCombo):
    pass


class RankCategoryCard(QFrame):
    clicked = Signal(str)

    _COLORS = [
        (QColor("#228563"), QColor("#32c496")),
        (QColor("#2a64aa"), QColor("#4e9df2")),
        (QColor("#ca5d31"), QColor("#f7a354")),
        (QColor("#cd3531"), QColor("#f76f53")),
        (QColor("#2a64aa"), QColor("#4e9df2")),
        (QColor("#228563"), QColor("#32c496")),
    ]

    def __init__(
        self,
        rank_id: str,
        title: str,
        subtitle: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._rank_id = rank_id
        self._title = title
        self._subtitle = subtitle
        self.setObjectName("categoryCard")
        self.setMinimumSize(110, 70)
        self.setFixedHeight(82)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        start_color, end_color = self._COLORS[
            abs(hash(self._rank_id)) % len(self._COLORS)
        ]
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, start_color)
        gradient.setColorAt(1.0, end_color)
        path = QPainterPath()
        path.addRoundedRect(rect, 30, 30)
        painter.fillPath(path, gradient)

        painter.setPen(QColor("#ffffff"))
        title_font = QFont("Microsoft YaHei UI", 14)
        title_font.setBold(True)
        painter.setFont(title_font)
        title_rect = QRectF(14, 16, rect.width() - 28, 30)
        title_text = QFontMetrics(title_font).elidedText(
            self._title,
            Qt.TextElideMode.ElideRight,
            int(title_rect.width()),
        )
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_text,
        )
        subtitle_font = QFont("Microsoft YaHei UI", 11)
        painter.setFont(subtitle_font)
        subtitle_rect = QRectF(14, 50, rect.width() - 28, 28)
        subtitle_text = QFontMetrics(subtitle_font).elidedText(
            self._subtitle,
            Qt.TextElideMode.ElideRight,
            int(subtitle_rect.width()),
        )
        painter.drawText(
            subtitle_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            subtitle_text,
        )

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._rank_id)
        super().mouseReleaseEvent(event)


class BannerCard(QFrame):
    clicked = Signal()

    _GRADIENTS = [
        (QColor("#7f1d1d"), QColor("#e8504f")),
        (QColor("#c62b2b"), QColor("#ff8a7a")),
        (QColor("#a82626"), QColor("#ff5f6d")),
    ]

    def __init__(self, index: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._index = index % len(self._GRADIENTS)
        self._title = ""
        self._subtitle = ""
        self._image: Optional[QImage] = None
        self.setMinimumWidth(300)
        self.setMaximumWidth(560)
        self.setFixedHeight(170)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, item: BannerItem) -> None:
        self._title = item.title
        self._subtitle = item.subtitle
        self.update()

    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        start_color, end_color = self._GRADIENTS[self._index]
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, start_color)
        gradient.setColorAt(1.0, end_color)
        path = QPainterPath()
        path.addRoundedRect(rect, 28, 28)
        painter.fillPath(path, gradient)

        if self._image is not None and not self._image.isNull():
            painter.save()
            painter.setClipPath(path)
            pixmap = QPixmap.fromImage(self._image).scaled(
                self.width(),
                self.height(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(0.92)
            painter.drawPixmap(rect.toRect(), pixmap)
            painter.setOpacity(1.0)
            overlay = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            overlay.setColorAt(0.0, QColor(0, 0, 0, 40))
            overlay.setColorAt(1.0, QColor(0, 0, 0, 190))
            painter.fillRect(rect, overlay)
            painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 220))
        radius = 26.0
        painter.drawEllipse(
            QRectF(rect.right() - 58, rect.center().y() - radius, radius * 2, radius * 2)
        )
        painter.setBrush(QColor("#ec4141"))
        painter.drawEllipse(
            QRectF(rect.right() - 53, rect.center().y() - radius + 5, radius * 2 - 10, radius * 2 - 10)
        )
        triangle = QPolygonF(
            [
                QPointF(rect.right() - 42, rect.center().y() - 7),
                QPointF(rect.right() - 28, rect.center().y()),
                QPointF(rect.right() - 42, rect.center().y() + 7),
            ]
        )
        painter.setBrush(QColor("#ffffff"))
        painter.drawPolygon(triangle)

        painter.setPen(QColor("#ffffff"))
        title_font = QFont("Microsoft YaHei UI", 17)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(
            QRectF(rect.left() + 18, rect.bottom() - 68, rect.width() - 90, 30),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._title,
        )
        painter.setFont(QFont("Microsoft YaHei UI", 12))
        painter.drawText(
            QRectF(rect.left() + 18, rect.bottom() - 38, rect.width() - 90, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._subtitle,
        )


class DiscoverPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._banner_tokens: Dict[str, BannerCard] = {}
        self._recommended_tokens: Dict[str, CoverCard] = {}
        self._official_tokens: Dict[str, CoverCard] = {}
        self._song_tokens: Dict[str, CoverCard] = {}
        self._album_cards: List[AlbumCard] = []
        self._new_songs: List[Song] = []
        self._playlist_page = 1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("scrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel("精选")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._refresh = QPushButton("换一批")
        self._refresh.setObjectName("swapButton")
        self._refresh.setToolTip("换一批精选歌单")
        self._refresh.clicked.connect(self.refresh)
        header.addWidget(self._refresh)
        layout.addLayout(header)

        self._recommended_section = self._section("推荐歌单")
        self._recommended_grid = QGridLayout()
        self._recommended_grid.setHorizontalSpacing(14)
        self._recommended_grid.setVerticalSpacing(16)
        self._recommended_section.addLayout(self._recommended_grid)
        self._recommended_section.addStretch(1)
        layout.addLayout(self._recommended_section)

        self._official_section = self._section("官方歌单")
        self._official_grid = QGridLayout()
        self._official_grid.setHorizontalSpacing(14)
        self._official_grid.setVerticalSpacing(16)
        self._official_section.addLayout(self._official_grid)
        self._official_section.addStretch(1)
        layout.addLayout(self._official_section)

        self._new_section = self._section("最新音乐")
        self._new_grid = QGridLayout()
        self._new_grid.setHorizontalSpacing(14)
        self._new_grid.setVerticalSpacing(16)
        self._new_section.addLayout(self._new_grid)
        self._new_section.addStretch(1)
        layout.addLayout(self._new_section)

        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)

        self._window.images.loaded.connect(self._on_image)

    def _section(self, text: str) -> QVBoxLayout:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        box = QVBoxLayout()
        box.setSpacing(10)
        box.addWidget(label)
        return box

    def load(self, page: int = 1) -> None:
        self._playlist_page = page
        self._refresh.setEnabled(False)
        self._window.run_task(
            f"discover_kugou:{page}",
            self._window.kugou.fetch_discover,
            self._fill_discover,
            page,
        )

    def refresh(self) -> None:
        next_page = self._playlist_page + 1
        self._window.show_toast(f"正在为你换一批精选歌单（第 {next_page} 批）")
        self.load(next_page)

    def _fill_discover(self, data: Dict[str, List]) -> None:
        playlists = data.get("playlists") or []
        self._fill_recommended(playlists[:3])
        self._fill_official(playlists[3:9])
        songs = data.get("songs") or []
        start = (self._playlist_page - 1) * 12
        batch = songs[start : start + 12]
        if len(batch) < 12:
            used = {song.key for song in batch}
            for song in songs:
                if len(batch) >= 12:
                    break
                if song.key not in used:
                    used.add(song.key)
                    batch.append(song)
        self._fill_new_songs(batch[:12])
        self._refresh.setEnabled(True)
        if self._playlist_page > 1:
            self._window.show_toast(
                f"已加载第 {self._playlist_page} 批精选歌单，共 {len(playlists)} 个歌单"
            )

    def _fill_recommended(self, cards: List[AlbumCard]) -> None:
        self._clear_layout(self._recommended_grid)
        self._recommended_tokens.clear()
        columns = 3
        for index, album in enumerate(cards):
            card = CoverCard(168)
            card.set_card(album.title, album.artist)
            card.clicked.connect(lambda a=album: self._play_album(a))
            token = f"recommended:{index}:{album.title}"
            self._recommended_tokens[token] = card
            if album.cover_url:
                self._window.images.load(token, album.cover_url)
            self._recommended_grid.addWidget(
                card, index // columns, index % columns, Qt.AlignmentFlag.AlignLeft
            )
        self._pad_grid(self._recommended_grid, len(cards), columns, 168)

    def _fill_official(self, cards: List[AlbumCard]) -> None:
        self._clear_layout(self._official_grid)
        self._official_tokens.clear()
        self._album_cards = list(cards)
        columns = 3
        for index, album in enumerate(cards):
            card = CoverCard(150)
            card.set_card(album.title, album.artist)
            card.clicked.connect(lambda a=album: self._play_album(a))
            token = f"official:{index}:{album.title}"
            self._official_tokens[token] = card
            if album.cover_url:
                self._window.images.load(token, album.cover_url)
            self._official_grid.addWidget(
                card, index // columns, index % columns, Qt.AlignmentFlag.AlignLeft
            )
        self._pad_grid(self._official_grid, len(cards), columns, 150)

    def _fill_new_songs(self, songs: List[Song]) -> None:
        self._clear_layout(self._new_grid)
        self._song_tokens.clear()
        self._new_songs = list(songs)
        columns = 4
        for index, song in enumerate(songs):
            card = CoverCard(140)
            card.set_card(song.title, song.artist)
            card.clicked.connect(lambda s=song: self._window.play_song(s))
            token = f"new:{index}:{song.key}"
            self._song_tokens[token] = card
            if song.cover_url:
                self._window.images.load(token, song.cover_url)
            elif song.cover_data:
                card.set_cover_data(song.cover_data)
            self._new_grid.addWidget(
                card, index // columns, index % columns, Qt.AlignmentFlag.AlignLeft
            )
        self._pad_grid(self._new_grid, len(songs), columns, 140)

    @staticmethod
    def _pad_grid(
        grid: QGridLayout, count: int, columns: int, cover_size: int
    ) -> None:
        missing = (-count) % columns
        for index in range(missing):
            card = CoverCard(cover_size)
            card.set_card("", "")
            position = count + index
            grid.addWidget(
                card,
                position // columns,
                position % columns,
                Qt.AlignmentFlag.AlignLeft,
            )

    def _play_album(self, album: AlbumCard) -> None:
        if not album.album_id:
            self._window.show_toast("这个歌单暂时无法打开")
            return

        def play_playlist(songs: List[Song]) -> None:
            if songs:
                self._window.play_songs(songs)
            else:
                self._window.show_toast("没有找到该歌单的可播放曲目")

        self._window.run_task(
            f"album_tracks:{album.album_id}",
            self._window.kugou.fetch_playlist_tracks,
            play_playlist,
            album.album_id,
        )

    def _on_image(self, token: str, image: QImage) -> None:
        if token in self._banner_tokens:
            self._banner_tokens[token].set_image(image)
        elif token in self._recommended_tokens:
            self._recommended_tokens[token].set_image(image)
        elif token in self._official_tokens:
            self._official_tokens[token].set_image(image)
        elif token in self._song_tokens:
            self._song_tokens[token].set_image(image)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                DiscoverPage._clear_layout(item.layout())


class LegacyChartsPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._songs: List[Song] = []
        self._rank_items: List[dict] = []
        self._rank_cards: List[tuple] = []
        self._category_cards: List[tuple] = []
        self._rank_tokens: Dict[str, CoverCard] = {}
        self._progress = ChartProgress(self)
        self._progress.changed.connect(self._on_match_progress)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("排行榜")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._status = QLabel("")
        self._status.setObjectName("statusText")
        header.addWidget(self._status)
        self._rank = QComboBox()
        self._rank.setMinimumWidth(190)
        self._refresh = IconButton("refresh", size=30)
        self._refresh.setToolTip("刷新榜单")
        header.addWidget(self._rank)
        header.addWidget(self._refresh)
        layout.addLayout(header)

        category_label = QLabel("热门分类")
        category_label.setObjectName("sectionTitle")
        layout.addWidget(category_label)

        category_scroll = QScrollArea()
        category_scroll.setWidgetResizable(True)
        category_scroll.setFrameShape(QFrame.Shape.NoFrame)
        category_scroll.setFixedHeight(100)
        category_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        category_content = QWidget()
        self._category_row = QHBoxLayout(category_content)
        self._category_row.setContentsMargins(0, 0, 0, 0)
        self._category_row.setSpacing(12)
        self._category_row.addStretch(1)
        category_scroll.setWidget(category_content)
        layout.addWidget(category_scroll)

        rank_header = QHBoxLayout()
        rank_label = QLabel("官方榜")
        rank_label.setObjectName("sectionTitle")
        rank_header.addWidget(rank_label)
        rank_header.addStretch(1)
        layout.addLayout(rank_header)

        rank_scroll = QScrollArea()
        rank_scroll.setWidgetResizable(True)
        rank_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rank_scroll.setFixedHeight(200)
        rank_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rank_content = QWidget()
        self._rank_row = QHBoxLayout(rank_content)
        self._rank_row.setContentsMargins(0, 0, 0, 0)
        self._rank_row.setSpacing(14)
        self._rank_row.addStretch(1)
        rank_scroll.setWidget(rank_content)
        layout.addWidget(rank_scroll)

        self._table = SongTable(window.images)
        self._table.play_requested.connect(self._on_play)
        self._table.like_toggled.connect(self._window.toggle_like)
        layout.addWidget(self._table, 1)
        self._playability_timer = QTimer(self)
        self._playability_timer.setSingleShot(True)
        self._playability_timer.setInterval(400)
        self._playability_timer.timeout.connect(self._table.update_playability)

        self._rank.currentIndexChanged.connect(self._on_rank_combo_changed)
        self._refresh.clicked.connect(self._reload)
        self._window.images.loaded.connect(self._on_rank_image)

    def load(self) -> None:
        self._load_ranks()

    def _load_ranks(self) -> None:
        self._status.setText("榜单加载中…")
        self._window.run_task(
            "rank_list",
            fetch_rank_list,
            self._fill_ranks,
        )

    def _fill_ranks(self, ranks: List[dict]) -> None:
        self._rank_items = list(ranks)
        self._rank.blockSignals(True)
        self._rank.clear()
        for item in self._rank_items:
            self._rank.addItem(
                _clean_rank_name(item.get("rankname") or "未知榜单"),
                item.get("rankid"),
            )
        self._rank.blockSignals(False)
        if not self._rank_items:
            self._status.setText("暂无榜单")
            self._table.set_songs([], self._window.liked_keys)
            return
        self._fill_categories(ranks)
        self._fill_rank_cards(ranks)
        self._rank.blockSignals(True)
        self._rank.setCurrentIndex(0)
        self._rank.blockSignals(False)
        self._update_selected_card(str(self._rank.currentData() or ""))
        self._reload()

    def _fill_categories(self, ranks: List[dict]) -> None:
        self._clear_layout(self._category_row)
        self._category_cards.clear()
        for index, item in enumerate(ranks[:6]):
            rank_id = str(item.get("rankid") or "")
            subtitle = (
                item.get("update_frequency")
                or (f"{item.get('track_count')} 首" if item.get("track_count") else "")
                or "官方榜"
            )
            card = RankCategoryCard(
                rank_id,
                _clean_rank_name(item.get("rankname") or "未知榜单"),
                subtitle,
            )
            card.clicked.connect(self._select_rank_by_id)
            self._category_cards.append((card, rank_id))
            self._category_row.addWidget(card)
        self._category_row.addStretch(1)

    def _fill_rank_cards(self, ranks: List[dict]) -> None:
        self._clear_layout(self._rank_row)
        self._rank_tokens.clear()
        self._rank_cards.clear()
        for index, item in enumerate(ranks[:12]):
            rank_id = str(item.get("rankid") or "")
            card = CoverCard(120)
            subtitle = (
                item.get("update_frequency")
                or (f"{item.get('track_count')} 首" if item.get("track_count") else "")
            )
            card.set_card(_clean_rank_name(item.get("rankname") or "未知榜单"), subtitle)
            card.clicked.connect(lambda it=item: self._select_rank(it))
            token = f"rank_card:{index}:{rank_id}"
            self._rank_tokens[token] = card
            cover = item.get("cover") or ""
            if cover:
                self._window.images.load(token, cover)
            self._rank_cards.append((card, rank_id))
            self._rank_row.addWidget(card)
        self._rank_row.addStretch(1)

    def _on_rank_image(self, token: str, image: QImage) -> None:
        card = self._rank_tokens.get(token)
        if card is not None:
            card.set_image(image)

    def _select_rank(self, item: dict) -> None:
        rank_id = str(item.get("rankid") or "")
        self._update_selected_card(rank_id)
        index = self._rank.findData(rank_id)
        if index >= 0:
            self._rank.blockSignals(True)
            self._rank.setCurrentIndex(index)
            self._rank.blockSignals(False)
        self._reload()

    def _select_rank_by_id(self, rank_id: str) -> None:
        for item in self._rank_items:
            if str(item.get("rankid") or "") == rank_id:
                self._select_rank(item)
                return

    def _update_selected_card(self, rank_id: str) -> None:
        for card, current_id in self._rank_cards:
            selected = current_id == rank_id
            card.setProperty("selected", selected)
            card.style().unpolish(card)
            card.style().polish(card)
        for card, current_id in self._category_cards:
            selected = current_id == rank_id
            card.setProperty("selected", selected)
            card.style().unpolish(card)
            card.style().polish(card)

    def _on_rank_combo_changed(self, _index: int) -> None:
        rank_id = str(self._rank.currentData() or "")
        self._update_selected_card(rank_id)
        self._reload()

    def _reload(self) -> None:
        rankid = self._rank.currentData()
        if not rankid:
            return
        self._status.setText("歌曲加载中…")
        self._window.run_task(
            "chart_songs",
            fetch_rank_songs,
            self._on_rank_songs,
            str(rankid),
        )

    def _on_rank_songs(self, songs: List[Song]) -> None:
        if not songs:
            self._songs = []
            self._table.set_songs([], self._window.liked_keys)
            self._status.setText("该榜单暂无歌曲")
            return
        self._songs = list(songs)
        self._table.set_songs(self._songs, self._window.liked_keys)
        self._status.setText(f"已同步 {len(self._songs)} 首，正在匹配网络音源…")
        self._window.run_task(
            "chart_match",
            match_rank_songs,
            self._on_matched,
            self._songs,
            self._progress.changed.emit,
        )

    def _on_matched(self, result) -> None:
        if isinstance(result, tuple) and len(result) >= 2:
            songs, matched = result[0], result[1]
        else:
            songs, matched = result, len(result)
        self._songs = list(songs)
        self._playability_timer.stop()
        self._table.update_playability()
        unmatched = max(0, len(self._songs) - int(matched))
        if unmatched:
            self._status.setText(
                f"同步 {len(self._songs)} 首 · 已匹配 {matched} 首 · {unmatched} 首暂无网络音源"
            )
        else:
            self._status.setText(f"同步 {len(self._songs)} 首 · 全部可播放")

    def _on_match_progress(self, message: str) -> None:
        self._status.setText(message)
        self._playability_timer.start()

    def _fill(self, songs: List[Song]) -> None:
        self._songs = list(songs)
        self._table.set_songs(self._songs, self._window.liked_keys)
        self._status.setText(f"{len(self._songs)} 首" if self._songs else "暂无数据")

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_play(self, songs: List[Song], index: int) -> None:
        song = songs[index] if 0 <= index < len(songs) else None
        if song is not None and not (song.kugou_hash or song.url or song.local_path):
            self._window.show_toast("该歌曲暂无网络音源，无法播放")
            return
        self._window.play_songs(songs, index)


def _format_count(value) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return "0"
    if number >= 100000000:
        return f"{number / 100000000:.1f}亿"
    if number >= 10000:
        return f"{number / 10000:.1f}万"
    return str(number)


def _clean_rank_name(name) -> str:
    text = str(name or "")
    return (
        text.replace("网易云音乐", "网络音乐")
        .replace("网易云", "网络")
        .replace("酷狗音乐", "网络音乐")
        .replace("酷狗", "网络")
    )


def _format_date(epoch_ms: int) -> str:
    try:
        return datetime.fromtimestamp(int(epoch_ms or 0) / 1000.0).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


class RoundedImageLabel(QLabel):
    def __init__(self, radius: float = 18.0, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._radius = radius
        self._image = QImage()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_image(self, image: QImage) -> None:
        self._image = QImage(image)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        if not self._image.isNull():
            pixmap = QPixmap.fromImage(self._image).scaled(
                self.width(),
                self.height(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset_x = (self.width() - pixmap.width()) // 2
            offset_y = (self.height() - pixmap.height()) // 2
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(offset_x, offset_y, pixmap)
            painter.restore()
        else:
            painter.fillPath(path, QColor(255, 255, 255, 10))


class RankHeader(QFrame):
    play_all_clicked = Signal()
    download_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("rankHeader")
        self.setFixedHeight(224)
        self._image: Optional[QImage] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(24)

        self._cover = RoundedImageLabel(radius=18.0)
        self._cover.setFixedSize(176, 176)
        layout.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignVCenter)

        info = QVBoxLayout()
        info.setSpacing(8)
        self._title = QLabel("官方榜单")
        self._title.setObjectName("rankTitle")
        self._title.setWordWrap(True)
        info.addWidget(self._title)

        self._desc = QLabel("")
        self._desc.setObjectName("rankDesc")
        self._desc.setWordWrap(True)
        info.addWidget(self._desc)

        self._date = QLabel("")
        self._date.setObjectName("rankDate")
        info.addWidget(self._date)

        self._stats = QLabel("")
        self._stats.setObjectName("rankStats")
        info.addWidget(self._stats)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self._play_all = QPushButton("播放全部")
        self._play_all.setObjectName("folderButton")
        self._play_all.clicked.connect(self.play_all_clicked.emit)
        buttons.addWidget(self._play_all)
        buttons.addStretch(1)
        info.addLayout(buttons)

        layout.addLayout(info, 1)

    def set_meta(self, meta: Dict) -> None:
        self._title.setText(_clean_rank_name(meta.get("rankname") or "官方榜单"))
        self._desc.setText(
            _clean_rank_name(
                meta.get("description")
                or "热门音乐排行榜，每日更新。"
            )
        )
        date_text = _format_date(meta.get("update_time") or 0)
        self._date.setText(f"更新于 {date_text}" if date_text else "")
        stats = []
        if meta.get("track_count"):
            stats.append(f"{meta.get('track_count')}首")
        if meta.get("play_count"):
            stats.append(f"{_format_count(meta.get('play_count'))}播放")
        if meta.get("subscribed_count"):
            stats.append(f"{_format_count(meta.get('subscribed_count'))}收藏者")
        if meta.get("comment_count"):
            stats.append(f"{_format_count(meta.get('comment_count'))}评论")
        self._stats.setText(" / ".join(stats))

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._cover.set_image(image)

    def set_downloading(self, downloading: bool) -> None:
        button = getattr(self, "_download", None)
        if button is not None:
            button.setEnabled(not downloading)
            button.setText("下载中…" if downloading else "下载")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#5a1f24"))
        gradient.setColorAt(0.55, QColor("#3a242a"))
        gradient.setColorAt(1.0, QColor("#242529"))
        path = QPainterPath()
        path.addRoundedRect(rect, 28, 28)
        painter.save()
        painter.setClipPath(path)
        painter.fillPath(path, gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(236, 65, 65, 24))
        painter.drawEllipse(
            QRectF(rect.right() - 220, rect.top() - 80, 320, 320)
        )
        painter.restore()


class RankSongCard(QFrame):
    clicked = Signal(str)

    _GRADIENTS = [
        (QColor("#2b2622"), QColor("#2b2622")),
        (QColor("#2b2622"), QColor("#2b2622")),
        (QColor("#2b2622"), QColor("#2b2622")),
        (QColor("#2b2622"), QColor("#2b2622")),
        (QColor("#2b2622"), QColor("#2b2622")),
        (QColor("#2b2622"), QColor("#2b2622")),
    ]

    def __init__(
        self,
        rank_id: str,
        title: str,
        subtitle: str = "",
        top_songs: Optional[List[dict]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._rank_id = rank_id
        self.setObjectName("rankSongCard")
        self.setFixedSize(280, 216)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(3)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._title = QLabel(title or "未知榜单")
        self._title.setObjectName("rankCardTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._freq = QLabel(subtitle)
        self._freq.setObjectName("rankCardFreq")
        self._freq.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._freq)
        layout.addLayout(header)

        for index, entry in enumerate(top_songs or []):
            if index >= 5:
                break
            row = QHBoxLayout()
            row.setSpacing(8)
            number = QLabel(str(index + 1))
            number.setObjectName("rankSongIndex")
            number.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(number)

            info = QVBoxLayout()
            info.setSpacing(0)
            name = QLabel(entry.get("title") or entry.get("first") or "")
            name.setObjectName("rankSongName")
            name.setWordWrap(True)
            info.addWidget(name)
            artist = QLabel(entry.get("artist") or entry.get("second") or "")
            artist.setObjectName("rankSongArtist")
            artist.setWordWrap(True)
            info.addWidget(artist)
            row.addLayout(info, 1)
            layout.addLayout(row)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        start_color, end_color = self._GRADIENTS[
            abs(hash(self._rank_id)) % len(self._GRADIENTS)
        ]
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, start_color)
        gradient.setColorAt(1.0, end_color)
        path = QPainterPath()
        path.addRoundedRect(rect, 30, 30)
        painter.fillPath(path, gradient)
        if self._hovered:
            painter.fillPath(path, QColor(255, 255, 255, 14))

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._rank_id)
        super().mouseReleaseEvent(event)


class ChartsPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._rank_items: List[dict] = []
        self._category_cards: List[tuple] = []
        self._rank_cards: List[tuple] = []
        self._rank_columns = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("排行榜")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._status = QLabel("")
        self._status.setObjectName("statusText")
        header.addWidget(self._status)
        layout.addLayout(header)

        category_label = QLabel("热门分类")
        category_label.setObjectName("sectionTitle")
        layout.addWidget(category_label)

        category_content = QWidget()
        self._category_row = QHBoxLayout(category_content)
        self._category_row.setContentsMargins(0, 0, 0, 0)
        self._category_row.setSpacing(12)
        layout.addWidget(category_content)

        rank_label = QLabel("官方榜")
        rank_label.setObjectName("sectionTitle")
        layout.addWidget(rank_label)

        rank_scroll = QScrollArea()
        rank_scroll.setWidgetResizable(True)
        rank_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rank_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        rank_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rank_content = QWidget()
        self._rank_grid = QGridLayout(rank_content)
        self._rank_grid.setContentsMargins(0, 0, 0, 0)
        self._rank_grid.setSpacing(14)
        self._rank_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        rank_scroll.setWidget(rank_content)
        layout.addWidget(rank_scroll, 1)

    def load(self) -> None:
        self._load_ranks()

    def _load_ranks(self) -> None:
        self._status.setText("榜单加载中…")
        self._window.run_task(
            "rank_list",
            fetch_rank_list,
            self._fill_ranks,
        )

    def _fill_ranks(self, ranks: List[dict]) -> None:
        self._rank_items = list(ranks)
        if not self._rank_items:
            self._status.setText("暂时没有可用的官方榜单")
            return
        self._fill_categories(self._rank_items)
        self._fill_rank_cards(self._rank_items)
        self._status.setText(f"共 {len(self._rank_items)} 个官方榜单")

    def _fill_categories(self, ranks: List[dict]) -> None:
        self._clear_layout(self._category_row)
        self._category_cards.clear()
        for item in ranks[:6]:
            rank_id = str(item.get("rankid") or "")
            subtitle = (
                item.get("update_frequency")
                or (f"{item.get('track_count')} 首" if item.get("track_count") else "")
                or "官方榜"
            )
            card = RankCategoryCard(
                rank_id,
                _clean_rank_name(item.get("rankname") or "未知榜单"),
                subtitle,
            )
            card.clicked.connect(self._open_rank_by_id)
            self._category_cards.append((card, rank_id))
            self._category_row.addWidget(card, 1)

    def _fill_rank_cards(self, ranks: List[dict]) -> None:
        self._clear_layout(self._rank_grid)
        self._rank_cards.clear()
        self._rank_columns = 0
        for item in ranks:
            rank_id = str(item.get("rankid") or "")
            subtitle = (
                item.get("update_frequency")
                or (f"{item.get('track_count')} 首" if item.get("track_count") else "")
                or "官方榜"
            )
            card = RankSongCard(
                rank_id,
                _clean_rank_name(item.get("rankname") or "未知榜单"),
                subtitle,
                item.get("top_songs") or [],
            )
            card.clicked.connect(lambda rid=rank_id: self._open_rank_by_id(rid))
            self._rank_cards.append((card, rank_id))
        self._reflow_rank_cards()

    def _reflow_rank_cards(self) -> None:
        if not self._rank_cards:
            return
        width = max(0, self.width() - 48)
        columns = max(2, (width + 14) // (280 + 14))
        columns = min(4, columns)
        if columns == self._rank_columns and self._rank_grid.count() == len(self._rank_cards):
            return
        while self._rank_grid.count():
            item = self._rank_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._rank_columns = columns
        for index, (card, _rank_id) in enumerate(self._rank_cards):
            self._rank_grid.addWidget(card, index // columns, index % columns)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_rank_grid", None) is None:
            return
        self._reflow_rank_cards()

    def _open_rank_by_id(self, rank_id: str) -> None:
        item = next(
            (r for r in self._rank_items if str(r.get("rankid") or "") == rank_id),
            {},
        )
        self._window.open_rank_detail(rank_id, item)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class RankDetailPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._rank_id = ""
        self._songs: List[Song] = []
        self._meta: Dict = {}
        self._progress = ChartProgress(self)
        self._download_progress = ChartProgress(self)
        self._progress.changed.connect(self._on_match_progress)
        self._download_progress.changed.connect(self._on_download_progress)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = RankHeader()
        self._header.play_all_clicked.connect(self._play_all)
        self._header.download_clicked.connect(self._download_all)
        layout.addWidget(self._header)

        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(24, 14, 24, 6)
        self._status = QLabel("")
        self._status.setObjectName("statusText")
        tool_row.addWidget(self._status)
        tool_row.addStretch(1)
        layout.addLayout(tool_row)

        self._table = SongTable(window.images)
        self._table.play_requested.connect(self._on_play)
        self._table.like_toggled.connect(self._window.toggle_like)
        layout.addWidget(self._table, 1)
        self._playability_timer = QTimer(self)
        self._playability_timer.setSingleShot(True)
        self._playability_timer.setInterval(400)
        self._playability_timer.timeout.connect(self._table.update_playability)

        self._window.images.loaded.connect(self._on_rank_image)

    def open_rank(self, rank_id: str, item: Optional[Dict] = None) -> None:
        self._rank_id = str(rank_id)
        self._meta = dict(item or {})
        self._meta["rankid"] = self._rank_id
        self._header.set_meta(self._meta)
        self._songs = []
        self._table.set_songs([], self._window.liked_keys)
        self._status.setText("正在同步网络榜单…")
        cover = self._meta.get("cover") or ""
        if cover:
            self._window.images.load(f"rank_cover:{self._rank_id}", cover)
        self._window.run_task(
            f"rank_detail:{self._rank_id}",
            fetch_rank_detail,
            self._on_detail,
            self._rank_id,
        )

    def _reload(self) -> None:
        if self._rank_id:
            self.open_rank(self._rank_id, self._meta)

    def _on_detail(self, result) -> None:
        if isinstance(result, tuple) and len(result) >= 2:
            songs, meta = result
        else:
            songs, meta = result, {}
        self._songs = list(songs)
        if isinstance(meta, dict):
            self._meta.update(meta)
        self._meta["rankid"] = self._rank_id
        self._header.set_meta(self._meta)
        cover = self._meta.get("cover") or ""
        if cover:
            self._window.images.load(f"rank_cover:{self._rank_id}", cover)
        if not self._songs:
            self._table.set_songs([], self._window.liked_keys)
            self._status.setText("该榜单暂时没有歌曲")
            return
        self._table.set_songs(self._songs, self._window.liked_keys)
        self._status.setText(
            f"已同步 {len(self._songs)} 首，正在匹配网络音源…"
        )
        self._window.run_task(
            f"rank_match:{self._rank_id}",
            match_rank_songs,
            self._on_matched,
            self._songs,
            self._progress.changed.emit,
        )

    def _on_matched(self, result) -> None:
        if isinstance(result, tuple) and len(result) >= 2:
            songs, matched = result[0], result[1]
        else:
            songs, matched = result, len(result)
        self._songs = list(songs)
        self._playability_timer.stop()
        self._table.update_playability()
        unmatched = max(0, len(self._songs) - int(matched))
        if unmatched:
            self._status.setText(
                f"同步 {len(self._songs)} 首 · 已匹配 {matched} 首 · "
                f"{unmatched} 首暂无网络音源"
            )
        else:
            self._status.setText(f"同步 {len(self._songs)} 首 · 全部可播放")

    def _on_match_progress(self, message: str) -> None:
        self._status.setText(message)
        self._playability_timer.start()

    def _on_rank_image(self, token: str, image: QImage) -> None:
        if token == f"rank_cover:{self._rank_id}":
            self._header.set_image(image)

    def _play_all(self) -> None:
        if self._songs:
            self._window.play_songs(self._songs, 0)

    def _download_all(self) -> None:
        if not self._songs:
            return
        self._header.set_downloading(True)
        self._status.setText("正在准备下载…")
        self._window.run_task(
            f"rank_download:{self._rank_id}",
            download_rank_songs,
            self._on_downloaded,
            self._songs,
            self._window.kugou.resolve_song_url,
            self._download_progress.changed.emit,
        )

    def _on_download_progress(self, message: str) -> None:
        self._status.setText(message)

    def _on_downloaded(self, result) -> None:
        self._header.set_downloading(False)
        if isinstance(result, tuple) and len(result) >= 2:
            ok, failures = result
        else:
            ok, failures = result, []
        if failures:
            self._status.setText(
                f"下载完成 {ok} 首，{len(failures)} 首失败，失败歌曲已跳过"
            )
            self._window.show_toast(
                f"下载完成 {ok} 首，{len(failures)} 首失败"
            )
        else:
            self._status.setText(f"已下载 {ok} 首到系统下载目录")
            self._window.show_toast(f"已下载 {ok} 首")

    def _on_play(self, songs: List[Song], index: int) -> None:
        song = songs[index] if 0 <= index < len(songs) else None
        if song is not None and not (song.kugou_hash or song.url or song.local_path):
            self._window.show_toast("该歌曲暂无网络音源，无法播放")
            return
        self._window.play_songs(songs, index)

class CoverGlow(QWidget):
    """Soft rounded backdrop that takes its tint from the current cover."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._base = QColor("#2c2522")
        self._glow = QColor(160, 90, 74)

    def set_cover(self, image: Optional[QImage]) -> None:
        if image is not None and not image.isNull():
            sample = image.scaled(
                1,
                1,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if not sample.isNull():
                color = sample.pixelColor(0, 0)
                self._base = QColor(
                    min(255, color.red() + 26),
                    min(255, color.green() + 22),
                    min(255, color.blue() + 20),
                )
                self._glow = QColor(
                    min(255, color.red() + 52),
                    min(255, color.green() + 36),
                    min(255, color.blue() + 30),
                )
        else:
            self._base = QColor("#2c2522")
            self._glow = QColor(160, 90, 74)
        self.update()

    def paintEvent(self, event) -> None:
        pass


class NowPlayingPage(QWidget):
    play_mode_changed = Signal(str)
    play_toggled = Signal()
    next_requested = Signal()
    prev_requested = Signal()
    queue_toggled = Signal()
    lyric_toggled = Signal()
    comment_toggled = Signal()
    like_toggled = Signal()
    volume_changed = Signal(float)
    seek_requested = Signal(int)
    quality_changed = Signal(str)

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._seeking = False
        self.setObjectName("nowPlayingPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(0)

        self._stage = QFrame()
        self._stage.setObjectName("nowPlayingCard")
        root.addWidget(self._stage, 1)
        layout = QHBoxLayout(self._stage)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(24)

        self._left_host = QWidget()
        self._left_host.setMinimumWidth(330)
        left = QVBoxLayout(self._left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)

        left.addStretch(1)
        vinyl_row = QHBoxLayout()
        vinyl_row.addStretch(1)
        self._glow = CoverGlow()
        glow_layout = QVBoxLayout(self._glow)
        glow_layout.setContentsMargins(0, 0, 0, 0)
        self._art = VinylDisc(size=340, needle=True)
        glow_layout.addWidget(self._art, 0, Qt.AlignmentFlag.AlignCenter)
        vinyl_row.addWidget(self._glow)
        vinyl_row.addStretch(1)
        left.addLayout(vinyl_row)

        progress = QHBoxLayout()
        progress.setSpacing(10)
        self._time = QLabel("00:00")
        self._time.setObjectName("timeText")
        self._time.setFixedWidth(46)
        self._time.setFixedHeight(18)
        progress.addWidget(self._time)
        self._seek = SeekSlider()
        self._seek.setRange(0, 0)
        self._seek.setFixedHeight(18)
        self._seek.sliderPressed.connect(self._on_seek_pressed)
        self._seek.sliderReleased.connect(self._on_seek_released)
        self._seek.sliderMoved.connect(self._on_seek_moved)
        progress.addWidget(self._seek, 1)
        self._duration = QLabel("00:00")
        self._duration.setObjectName("timeText")
        self._duration.setFixedWidth(46)
        self._duration.setFixedHeight(18)
        self._duration.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        progress.addWidget(self._duration)
        left.addLayout(progress)

        self._play_mode = IconButton("order", size=28)
        self._play_mode.set_icon_color(QColor("#ffffff"))
        self._play_mode.setToolTip("顺序播放")
        self._play_mode.clicked.connect(self._cycle_play_mode)
        self._prev = IconButton("prev", size=34)
        self._prev.set_icon_color(QColor("#ffffff"))
        self._prev.setToolTip("上一首")
        self._prev.clicked.connect(self.prev_requested.emit)
        self._play = IconButton("play", size=52)
        self._play.set_solid_background(QColor("#ff3333"))
        self._play.set_icon_color(QColor("#ffffff"))
        self._play.setToolTip("播放 / 暂停")
        self._play.clicked.connect(self.play_toggled.emit)
        self._next = IconButton("next", size=34)
        self._next.set_icon_color(QColor("#ffffff"))
        self._next.setToolTip("下一首")
        self._next.clicked.connect(self.next_requested.emit)
        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)
        controls_row.addStretch(1)
        controls_row.addWidget(self._play_mode)
        controls_row.addWidget(self._prev)
        controls_row.addWidget(self._play)
        controls_row.addWidget(self._next)
        controls_row.addStretch(1)
        left.addLayout(controls_row)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self._volume = VolumeControl(size=28)
        self._volume.volume_changed.connect(self.volume_changed.emit)
        bottom.addWidget(self._volume)
        self._quality = QualityCombo()
        self._quality.setObjectName("qualityCombo")
        self._quality.setFixedWidth(112)
        self._quality.addItem("128kbps", "128")
        self._quality.addItem("320kbps", "320")
        self._quality.addItem("无损FLAC", "flac")
        self._quality.addItem("Hi-Res", "high")
        self._quality.currentIndexChanged.connect(self._on_quality_changed)
        bottom.addWidget(self._quality)
        bottom.addStretch(1)
        left.addLayout(bottom)
        left.addStretch(1)

        layout.addWidget(self._left_host, 3)

        self._right_host = QWidget()
        self._right_host.setMinimumWidth(360)
        right = QVBoxLayout(self._right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        info_box = QVBoxLayout()
        info_box.setSpacing(4)
        self._title = QLabel("未在播放")
        self._title.setObjectName("nowPlayingTitle")
        self._title.setWordWrap(True)
        info_box.addWidget(self._title)

        meta = QVBoxLayout()
        meta.setSpacing(2)
        self._artist_value = QLabel("")
        self._album_value = QLabel("")
        self._source_value = QLabel("")
        self._meta_rows: List[tuple] = []
        for key, value_label in (
            ("歌手：", self._artist_value),
            ("专辑：", self._album_value),
            ("来源：", self._source_value),
        ):
            value_label.setObjectName("metaValue")
            value_label.setWordWrap(True)
            meta.addWidget(value_label)
            self._meta_rows.append((key, value_label))
        info_box.addLayout(meta)
        top.addLayout(info_box, 1)
        self._like = IconButton("heart", size=32)
        self._like.set_icon_color(QColor("#ffffff"))
        self._like.clicked.connect(self.like_toggled.emit)
        self._like_count = 0
        top.addWidget(self._like)
        self._comment = IconButton("comment", size=32)
        self._comment.set_icon_color(QColor("#ffffff"))
        self._comment.setToolTip("评论")
        self._comment.clicked.connect(self.comment_toggled.emit)
        top.addWidget(self._comment)
        self._queue = IconButton("queue", size=32)
        self._queue.set_icon_color(QColor("#ffffff"))
        self._queue.setToolTip("播放队列")
        self._queue.clicked.connect(self.queue_toggled.emit)
        top.addWidget(self._queue)
        self._lyric = IconButton("lyric", size=32)
        self._lyric.set_icon_color(QColor("#ffffff"))
        self._lyric.setToolTip("歌词面板")
        self._lyric.clicked.connect(self.lyric_toggled.emit)
        top.addWidget(self._lyric)
        right.addLayout(top)

        lyric_header = QHBoxLayout()
        lyric_title = QLabel("歌词")
        lyric_title.setObjectName("lyricSectionTitle")
        lyric_header.addWidget(lyric_title)
        self._lyric_hint = QLabel("")
        self._lyric_hint.setObjectName("subText")
        lyric_header.addWidget(self._lyric_hint)
        lyric_header.addStretch(1)
        right.addLayout(lyric_header)

        self._lyrics = LyricView()
        self._lyrics.seek_requested.connect(self.seek_requested)
        right.addWidget(self._lyrics, 1)

        layout.addWidget(self._right_host, 3)

        self._image_token = "now_playing_cover"
        self._window.images.loaded.connect(self._on_image_loaded)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Derive the disc size from the top-level window.  The page height and
        # the stage/left column sizes respond to the disc itself, so using
        # them creates an endless resize loop while the record is visible.
        win = self.window()
        if win is not None and win is not self:
            page_w = max(0, win.width())
            page_h = max(0, win.height())
        else:
            page_w = max(0, self.width())
            page_h = max(0, self.height())
        stage_h = max(0, page_h - 24)
        left_w = max(0.0, (page_w - 96) / 2.0)
        disc_size = max(
            120,
            min(int(min((stage_h - 170) * 0.92, left_w * 0.88)), 560),
        )
        glow_size = disc_size
        if glow_size != self._glow.width():
            self._glow.setFixedSize(glow_size, glow_size)
        if disc_size != self._art._size:
            self._art.set_size(disc_size)

    def set_song(self, song: Optional[Song], liked: bool = False) -> None:
        if song is None:
            self._title.setText("未在播放")
            self._artist_value.setText("")
            self._album_value.setText("")
            self._source_value.setText("")
            for _, value_label in self._meta_rows:
                value_label.hide()
            self._art.set_image(QImage())
            self._art.set_label_text("")
            self._lyrics.set_lines([])
            self._like.set_icon("heart")
            self._like.setToolTip("喜欢")
            return
        self._title.setText(song.title)
        self._art.set_label_text(song.title)
        for (key, value_label), (_, value) in zip(
            self._meta_rows,
            (
                ("歌手", song.artist),
                ("专辑", song.album),
                ("来源", song.source or "来源于网络"),
            ),
        ):
            if value:
                value_label.show()
                value_label.setText(f"{key}{value}")
            else:
                value_label.hide()
                value_label.setText("")
        self._like.set_icon("heart_fill" if liked else "heart")
        if self._like_count > 0:
            self._like.setToolTip(f"喜欢 {self._like_count}")
        else:
            self._like.setToolTip("喜欢")
        if song.cover_data:
            self._art.set_cover_data(song.cover_data)
            image = QImage()
            if image.loadFromData(song.cover_data):
                self._glow.set_cover(image)
        elif song.cover_url:
            self._window.images.load(self._image_token, song.cover_url)
        else:
            self._art.set_image(QImage())
            self._glow.set_cover(QImage())
        self._lyrics.set_lines([])

    def set_lyrics(self, lines: List[LyricLine]) -> None:
        self._lyrics.set_lines(lines)
        self._lyric_hint.setText(f"{len(lines)} 行" if lines else "")

    def set_position(self, position_ms: int) -> None:
        if not self._seeking:
            value = max(0, int(position_ms))
            if value != self._seek.value():
                self._seek.blockSignals(True)
                self._seek.setValue(value)
                self._seek.blockSignals(False)
        text = f"{position_ms // 60000:02d}:{(position_ms // 1000) % 60:02d}"
        if self._time.text() != text:
            self._time.setText(text)
        self._lyrics.set_position(position_ms)

    def set_duration(self, duration_ms: int) -> None:
        self._seek.blockSignals(True)
        self._seek.setMaximum(max(0, duration_ms))
        self._seek.setValue(min(self._seek.value(), max(0, duration_ms)))
        self._seek.blockSignals(False)
        text = f"{duration_ms // 60000:02d}:{(duration_ms // 1000) % 60:02d}"
        if self._duration.text() != text:
            self._duration.setText(text)

    def set_state(self, state: str) -> None:
        self._play.set_icon("pause" if state == "playing" else "play")
        self._art.set_spinning(state == "playing")
        self._art.set_needle_active(state == "playing")

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

    def set_liked(self, liked: bool) -> None:
        self._like.set_icon("heart_fill" if liked else "heart")

    def set_like_count(self, count: int) -> None:
        self._like_count = max(0, int(count or 0))
        if self._like_count > 0:
            self._like.setToolTip(f"喜欢 {self._like_count}")
        else:
            self._like.setToolTip("喜欢")

    def set_quality(self, quality: str) -> None:
        index = self._quality.findData(quality)
        self._quality.blockSignals(True)
        self._quality.setCurrentIndex(max(0, index))
        self._quality.blockSignals(False)

    def _on_quality_changed(self) -> None:
        quality = str(self._quality.currentData() or "")
        if quality:
            self.quality_changed.emit(quality)

    def _on_image_loaded(self, token: str, image: QImage) -> None:
        if token == self._image_token:
            self._art.set_image(image)
            self._glow.set_cover(image)

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _on_seek_released(self) -> None:
        self._seeking = False
        self.seek_requested.emit(self._seek.value())

    def _on_seek_moved(self, value: int) -> None:
        self._time.setText(
            f"{value // 60000:02d}:{(value // 1000) % 60:02d}"
        )
        self.seek_requested.emit(value)


class SearchPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        self._title = QLabel("搜索")
        self._title.setObjectName("pageTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._status = QLabel("")
        self._status.setObjectName("statusText")
        header.addWidget(self._status)
        layout.addLayout(header)

        self._empty = QLabel("输入关键词搜索在线歌曲")
        self._empty.setObjectName("emptyLabel")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty, 1)

        self._table = SongTable(window.images)
        self._table.play_requested.connect(self._on_play)
        self._table.like_toggled.connect(self._window.toggle_like)
        layout.addWidget(self._table, 1)
        self._table.hide()

    def start_search(self, term: str) -> None:
        term = term.strip()
        if not term:
            return
        self._title.setText(f"搜索：{term}")
        self._status.setText("搜索中…")
        self._table.hide()
        self._empty.show()
        self._empty.setText("正在搜索…")
        self._window.run_task(
            "search",
            self._window.kugou.search_songs,
            self._fill,
            term,
        )

    def _fill(self, result) -> None:
        if isinstance(result, tuple):
            songs, message = result
        else:
            songs, message = result, ""
        if not songs:
            self._table.hide()
            self._empty.show()
            self._empty.setText(message or "没有找到相关歌曲")
            self._status.setText(message or "0 首")
            return
        self._empty.hide()
        self._table.show()
        self._table.set_songs(songs, self._window.liked_keys)
        self._status.setText(message or f"{len(songs)} 首")

    def _on_play(self, songs: List[Song], index: int) -> None:
        self._window.play_songs(songs, index)


class LibraryPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._songs: List[Song] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("本地音乐")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._path = QLabel("尚未选择音乐文件夹")
        self._path.setObjectName("subText")
        self._path.setMaximumWidth(360)
        header.addWidget(self._path)
        self._count = QLabel("")
        self._count.setObjectName("statusText")
        header.addWidget(self._count)
        self._choose = QPushButton("选择文件夹")
        self._choose.setObjectName("folderButton")
        self._choose.clicked.connect(self._choose_folder)
        header.addWidget(self._choose)
        self._refresh_btn = IconButton("refresh", size=30)
        self._refresh_btn.setToolTip("重新扫描")
        self._refresh_btn.clicked.connect(self._rescan)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        self._table = SongTable(window.images)
        self._table.play_requested.connect(self._on_play)
        self._table.like_toggled.connect(self._window.toggle_like)
        layout.addWidget(self._table, 1)

    def start_scan(self, path: str) -> None:
        self._path.setText(path)
        self._count.setText("扫描中…")
        self._window.start_scan(path)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择音乐文件夹")
        if folder:
            self.start_scan(folder)

    def _rescan(self) -> None:
        if self._window.music_folder:
            self.start_scan(self._window.music_folder)

    def set_scan_result(self, songs: List[Song]) -> None:
        self._songs = list(songs)
        self._table.set_songs(self._songs, self._window.liked_keys)
        self._count.setText(f"{len(self._songs)} 首")

    def set_scan_error(self, message: str) -> None:
        self._count.setText("扫描失败")
        self._window.show_toast(f"扫描失败：{message}")

    def _on_play(self, songs: List[Song], index: int) -> None:
        self._window.play_songs(songs, index)


class FavoritesPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("我喜欢的音乐")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._count = QLabel("0 首")
        self._count.setObjectName("statusText")
        header.addWidget(self._count)
        layout.addLayout(header)

        self._empty = QLabel("还没有喜欢的歌曲")
        self._empty.setObjectName("emptyLabel")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty, 1)

        self._table = SongTable(window.images)
        self._table.play_requested.connect(self._on_play)
        self._table.like_toggled.connect(self._window.toggle_like)
        layout.addWidget(self._table, 1)
        self._table.hide()

    def refresh(self) -> None:
        songs = self._window.liked_songs
        self._count.setText(f"{len(songs)} 首")
        if not songs:
            self._table.hide()
            self._empty.show()
            return
        self._empty.hide()
        self._table.show()
        self._table.set_songs(songs, self._window.liked_keys)

    def _on_play(self, songs: List[Song], index: int) -> None:
        self._window.play_songs(songs, index)


class KugouPage(QWidget):
    login_changed = Signal()

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._qr_key = ""
        self._polling = False
        self._validating = False
        self._syncing = False

        self._qr_timer = QTimer(self)
        self._qr_timer.setInterval(2000)
        self._qr_timer.timeout.connect(self._poll_qr)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("scrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("账号登录")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._status = QLabel("")
        self._status.setObjectName("statusText")
        header.addWidget(self._status)
        layout.addLayout(header)

        panel = QFrame()
        panel.setObjectName("kugouPanel")
        panel.setMaximumWidth(520)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(26, 22, 26, 24)
        panel_layout.setSpacing(14)

        self._panel_title = QLabel("账号登录")
        self._panel_title.setObjectName("guideTitle")
        self._panel_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._panel_title)

        self._qr_label = QLabel()
        self._qr_label.setFixedSize(240, 240)
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setStyleSheet(
            "background: #ffffff; border-radius: 8px; padding: 8px;"
        )
        panel_layout.addWidget(self._qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        self._account_label = QLabel("")
        self._account_label.setObjectName("subText")
        self._account_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._account_label.setWordWrap(True)
        panel_layout.addWidget(self._account_label)

        self._member_card = QFrame()
        self._member_card.setObjectName("memberCard")
        self._member_card.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Minimum,
        )
        member_layout = QVBoxLayout(self._member_card)
        member_layout.setContentsMargins(16, 12, 16, 12)
        member_layout.setSpacing(5)
        member_title = QLabel("会员信息")
        member_title.setObjectName("memberCardTitle")
        member_layout.addWidget(member_title)
        self._member_status = QLabel("会员状态：--")
        self._member_expire = QLabel("到期时间：--")
        self._member_days = QLabel("剩余天数：--")
        for label in (
            self._member_status,
            self._member_expire,
            self._member_days,
        ):
            label.setObjectName("memberRow")
            label.setWordWrap(True)
            member_layout.addWidget(label)
        self._member_card.hide()
        panel_layout.addWidget(self._member_card)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self._refresh_qr_btn = QPushButton("重新获取二维码")
        self._refresh_qr_btn.setObjectName("normalButton")
        self._refresh_qr_btn.clicked.connect(self._generate_qr)
        actions.addWidget(self._refresh_qr_btn)

        self._sync_btn = QPushButton("同步会员信息")
        self._sync_btn.setObjectName("normalButton")
        self._sync_btn.clicked.connect(self._sync_member)
        actions.addWidget(self._sync_btn)

        self._logout_btn = QPushButton("退出登录")
        self._logout_btn.setObjectName("textButton")
        self._logout_btn.clicked.connect(self._logout)
        actions.addWidget(self._logout_btn)
        actions.addStretch(1)
        panel_layout.addLayout(actions)

        layout.addWidget(panel, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)

    def load(self) -> None:
        if self._window.kugou.logged_in:
            self._show_account()
        else:
            self._generate_qr()

    def _show_account(self) -> None:
        self._stop_polling()
        client = self._window.kugou
        self._panel_title.setText("已登录账号")
        self._account_label.setText(
            f"{client.nickname}\n用户 ID：{client.user_id()}"
        )
        self._qr_label.hide()
        self._account_label.show()
        self._refresh_qr_btn.hide()
        self._logout_btn.show()
        self._sync_btn.show()
        self._member_card.show()
        self._update_member_view(client.member_info)
        self._status.setText("已登录，可同步会员信息")
        self.login_changed.emit()
        self._validate_login()

    def _validate_login(self) -> None:
        if not self._window.kugou.logged_in or self._validating:
            return
        self._validating = True
        self._status.setText("正在校验登录状态…")
        self._window.run_task(
            "kugou_validate",
            self._window.kugou.validate_login,
            self._on_validate,
        )

    def _on_validate(self, valid: bool) -> None:
        self._validating = False
        if valid:
            self._status.setText("已登录，可同步会员信息")
            self._sync_member()
            return
        self._handle_invalid_login("登录状态已失效，请重新使用酷狗概念版扫码登录")

    def _handle_invalid_login(self, message: str) -> None:
        self._window.kugou.clear_login()
        self._window.show_toast(message)
        self.login_changed.emit()
        self._generate_qr()

    def _generate_qr(self) -> None:
        self._stop_polling()
        self._qr_key = ""
        self._qr_label.clear()
        self._qr_label.show()
        self._account_label.hide()
        self._sync_btn.hide()
        self._member_card.hide()
        self._refresh_qr_btn.show()
        self._logout_btn.hide()
        self._panel_title.setText("账号登录")
        self._status.setText("正在生成二维码…")
        self._window.run_task(
            "kugou_qr",
            self._window.kugou.qr_key,
            self._on_qr_key,
        )

    def _on_qr_key(self, payload: Dict[str, str]) -> None:
        key = payload.get("key") or ""
        image = payload.get("image") or ""
        if not key or not image:
            self._status.setText("获取二维码失败，请重试")
            return
        self._qr_key = key
        try:
            encoded = image.split(",", 1)[-1]
            raw = base64.b64decode(encoded)
            qr_image = QImage.fromData(raw)
            pixmap = QPixmap.fromImage(qr_image).scaled(
                220,
                220,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if pixmap.isNull():
                raise ValueError("empty qr image")
            self._qr_label.setPixmap(pixmap)
        except Exception:
            self._status.setText("二维码图片解析失败，请重试")
            return
        self._status.setText("请使用酷狗概念版扫码登录")
        self._qr_timer.start()

    def _poll_qr(self) -> None:
        if self._polling or not self._qr_key:
            return
        self._polling = True
        self._window.run_task(
            "kugou_qr_check",
            self._window.kugou.qr_check,
            self._on_qr_check,
            self._qr_key,
        )

    def _on_qr_check(self, result) -> None:
        self._polling = False
        if not isinstance(result, tuple) or len(result) < 2:
            return
        status, _payload = result
        if status == 2:
            self._status.setText("已扫码，请在酷狗概念版确认登录")
        elif status == 4:
            self._stop_polling()
            self._window.show_toast("登录成功")
            self._show_account()
        elif status == 0:
            self._stop_polling()
            self._status.setText("二维码已过期，请重新获取")

    def _sync_member(self) -> None:
        if not self._window.kugou.logged_in or self._syncing:
            return
        self._syncing = True
        self._sync_btn.setEnabled(False)
        self._status.setText("正在同步会员信息…")
        self._window.run_task(
            "kugou_member_sync",
            self._window.kugou.sync_member_info,
            self._on_member_synced,
        )

    def _on_member_synced(self, result) -> None:
        self._syncing = False
        self._sync_btn.setEnabled(True)
        if not self._window.kugou.logged_in:
            return
        if isinstance(result, tuple):
            ok, info = result
        else:
            ok, info = False, {}
        message = info.get("message") or ("会员信息已同步" if ok else "同步会员信息失败")
        if not ok and self._is_login_error(message):
            self._handle_invalid_login(message)
            return
        self._update_member_view(info)
        self._status.setText(message)
        self.login_changed.emit()
        if not ok:
            self._window.show_toast(message)

    def _update_member_view(self, info=None) -> None:
        if info is None:
            info = self._window.kugou.member_info
        is_vip = bool(info.get("is_vip"))
        vip_list = info.get("vip_list") or []
        if not isinstance(vip_list, list) or not vip_list:
            vip_list = []
        vip_list = vip_list[:1]
        if vip_list:
            names = "、".join(
                str(entry.get("name") or "")
                for entry in vip_list
                if entry.get("is_vip")
            )
            expire_text = "；".join(
                str(entry.get("vip_expire") or "暂无")
                for entry in vip_list
            )
            days_parts = []
            for entry in vip_list:
                days = entry.get("vip_days")
                days_text = f"{days} 天" if days not in (None, "") else "暂无"
                days_parts.append(days_text)
            days_text = "；".join(days_parts)
            status_text = names or ("概念版会员" if is_vip else "普通用户")
        else:
            vip_name = info.get("vip_name") or ("概念版会员" if is_vip else "普通用户")
            status_text = vip_name
            expire_text = info.get("vip_expire") or "暂无"
            days = info.get("vip_days")
            days_text = f"{days} 天" if days not in (None, "") else "暂无"
        self._member_status.setText(f"会员状态：{status_text}")
        self._member_expire.setText(f"到期时间：{expire_text}")
        self._member_days.setText(f"剩余天数：{days_text}")
        for label in (
            self._member_status,
            self._member_expire,
            self._member_days,
        ):
            hint = label.sizeHint().height()
            if hint > label.minimumHeight():
                label.setMinimumHeight(hint)

    def _is_login_error(self, message: str) -> bool:
        return any(
            key in message
            for key in ("登录状态已失效", "登录状态或设备信息无效", "请重新登录")
        )

    def _logout(self) -> None:
        self._window.kugou.clear_login()
        self._window.show_toast("已退出账号")
        self.login_changed.emit()
        self._generate_qr()

    def _stop_polling(self) -> None:
        self._polling = False
        if self._qr_timer.isActive():
            self._qr_timer.stop()

    def notify_task_failed(self, token: str) -> None:
        if token == "kugou_qr_check":
            self._polling = False
            self._stop_polling()
            self._status.setText("二维码检测失败，请重新获取")
        elif token == "kugou_qr":
            self._status.setText("获取二维码失败，请重试")
        elif token == "kugou_validate":
            self._validating = False
            self._status.setText("登录校验失败，请稍后重试")
        elif token == "kugou_member_sync":
            self._syncing = False
            self._sync_btn.setEnabled(True)
            self._status.setText("同步会员信息失败，请重试")


class SettingsPage(QWidget):
    quality_changed = Signal(str)
    output_device_changed = Signal(str)

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("scrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 26)
        layout.setSpacing(16)

        title = QLabel("设置")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        playback_card, playback_box = self._card("播放与音质", "选择可用的音质，切换后会自动重新加载当前歌曲")
        quality_row = QHBoxLayout()
        quality_row.setSpacing(12)
        quality_hint = QLabel("当前音质")
        quality_hint.setObjectName("settingsKey")
        quality_row.addWidget(quality_hint)
        quality_row.addStretch(1)
        self._quality = QualityCombo()
        self._quality.setObjectName("qualityCombo")
        self._quality.setMinimumWidth(160)
        self._quality.addItem("流畅 128kbps", "128")
        self._quality.addItem("高品质 320kbps", "320")
        self._quality.addItem("无损 FLAC", "flac")
        self._quality.addItem("Hi-Res", "high")
        self._quality.currentIndexChanged.connect(self._on_quality_changed)
        quality_row.addWidget(self._quality)
        playback_box.addLayout(quality_row)
        layout.addWidget(playback_card)

        device_card, device_box = self._card(
            "扬声器", "选择音频输出设备，切换后立即生效"
        )
        device_row = QHBoxLayout()
        device_row.setSpacing(12)
        device_hint = QLabel("输出设备")
        device_hint.setObjectName("settingsKey")
        device_row.addWidget(device_hint)
        device_row.addStretch(1)
        self._device = SpeakerCombo()
        self._device.setObjectName("deviceCombo")
        self._device.setMinimumWidth(220)
        self._device.currentIndexChanged.connect(self._on_device_changed)
        device_row.addWidget(self._device)
        device_box.addLayout(device_row)
        layout.addWidget(device_card)

        library_card, library_box = self._card("本地音乐", "管理本地歌曲文件夹，扫描结果会出现在侧边栏的本地音乐中")
        library_row = QHBoxLayout()
        library_row.setSpacing(12)
        self._folder_value = QLabel("尚未选择音乐文件夹")
        self._folder_value.setObjectName("settingsValue")
        self._folder_value.setWordWrap(True)
        library_row.addWidget(self._folder_value, 1)
        self._folder_btn = QPushButton("选择文件夹")
        self._folder_btn.setObjectName("normalButton")
        self._folder_btn.clicked.connect(self._choose_folder)
        library_row.addWidget(self._folder_btn)
        self._rescan_btn = QPushButton("重新扫描")
        self._rescan_btn.setObjectName("textButton")
        self._rescan_btn.clicked.connect(self._rescan)
        library_row.addWidget(self._rescan_btn)
        library_box.addLayout(library_row)
        layout.addWidget(library_card)

        account_card, account_box = self._card("账号", "使用酷狗概念版扫码登录后，可在账号页面同步会员信息")
        account_row = QHBoxLayout()
        account_row.setSpacing(12)
        self._account_value = QLabel("未登录")
        self._account_value.setObjectName("settingsValue")
        account_row.addWidget(self._account_value, 1)
        self._login_btn = QPushButton("前往登录")
        self._login_btn.setObjectName("folderButton")
        self._login_btn.clicked.connect(lambda: self._window._show_page(5))
        account_row.addWidget(self._login_btn)
        self._logout_btn = QPushButton("退出登录")
        self._logout_btn.setObjectName("textButton")
        self._logout_btn.clicked.connect(self._logout)
        account_row.addWidget(self._logout_btn)
        account_box.addLayout(account_row)
        layout.addWidget(account_card)

        def _link_label(text: str, url: str) -> QLabel:
            label = QLabel(
                f'<a href="{url}" style="color:#ec4141; text-decoration:none;">{text}</a>'
            )
            label.setOpenExternalLinks(True)
            label.setTextInteractionFlags(Qt.TextBrowserInteraction)
            return label

        about_card, about_box = self._card("关于 Meemaw music", "网络音乐播放器")
        about_box.addWidget(QLabel("版本 1.0.0"))
        about_box.addWidget(QLabel("开发者：MASK323"))
        about_box.addWidget(
            _link_label("GitHub 主页：https://github.com/MASK323", "https://github.com/MASK323")
        )
        about_box.addWidget(
            _link_label(
                "项目地址：https://github.com/MASK323/Meemaw-music",
                "https://github.com/MASK323/Meemaw-music",
            )
        )
        about_box.addWidget(QLabel("榜单数据：来源于网络 · 播放音源：来源于网络"))
        layout.addWidget(about_card)

        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)

        self.refresh_account()
        self._devices_loaded = False
        if self._window.music_folder:
            self._folder_value.setText(self._window.music_folder)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._devices_loaded:
            QTimer.singleShot(0, self._lazy_refresh_devices)

    def _lazy_refresh_devices(self) -> None:
        if self._devices_loaded:
            return
        self.refresh_output_devices(self._window.output_device)

    @staticmethod
    def _card(title: str, desc: str):
        card = QFrame()
        card.setObjectName("settingsCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("settingsCardTitle")
        box.addWidget(title_label)
        desc_label = QLabel(desc)
        desc_label.setObjectName("settingsCardDesc")
        desc_label.setWordWrap(True)
        box.addWidget(desc_label)
        return card, box

    def set_quality(self, quality: str) -> None:
        index = self._quality.findData(quality)
        self._quality.blockSignals(True)
        self._quality.setCurrentIndex(max(0, index))
        self._quality.blockSignals(False)

    def refresh_output_devices(self, selected_id: str = "") -> None:
        devices = QMediaDevices.audioOutputs()
        default = QMediaDevices.defaultAudioOutput()
        default_name = default.description() if not default.isNull() else ""
        preferred = selected_id or ""
        self._device.blockSignals(True)
        self._device.clear()
        if not devices:
            self._device.addItem("未检测到输出设备", "")
        for device in devices:
            label = device.description() or "未知设备"
            if device.isDefault():
                label += "（默认）"
            self._device.addItem(label, device.description())
            if not preferred and device.isDefault():
                preferred = device.description()
        if not preferred:
            preferred = default_name
        index = self._device.findData(preferred)
        if index < 0 and self._device.count() > 0:
            index = 0
        self._device.setCurrentIndex(max(0, index))
        self._device.blockSignals(False)
        self._devices_loaded = True

    def set_output_device(self, device_id: str) -> None:
        index = self._device.findData(device_id or "")
        if index >= 0:
            self._device.blockSignals(True)
            self._device.setCurrentIndex(index)
            self._device.blockSignals(False)
        elif self._device.count() == 0:
            self.refresh_output_devices(device_id)

    def refresh_account(self) -> None:
        client = self._window.kugou
        if client.logged_in:
            info = client.member_info
            vip_list = info.get("vip_list") or []
            if isinstance(vip_list, list) and vip_list:
                vip_name = "、".join(
                    str(entry.get("name") or "")
                    for entry in vip_list
                    if entry.get("is_vip")
                ) or "普通用户"
            else:
                vip_name = info.get("vip_name") or (
                    "概念版会员" if info.get("is_vip") else "普通用户"
                )
            expire = info.get("vip_expire") or ""
            suffix = f" · {vip_name}"
            if expire:
                suffix += f" · 到期 {expire}"
            self._account_value.setText(
                f"已登录：{client.nickname}（{client.user_id()}）{suffix}"
            )
            self._login_btn.hide()
            self._logout_btn.show()
        else:
            self._account_value.setText("未登录")
            self._login_btn.show()
            self._logout_btn.hide()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择音乐文件夹")
        if folder:
            self._window.start_scan(folder)
            self._folder_value.setText(folder)

    def _rescan(self) -> None:
        if self._window.music_folder:
            self._window.start_scan(self._window.music_folder)
        else:
            self._choose_folder()

    def _logout(self) -> None:
        self._window.kugou.clear_login()
        self._window.show_toast("已退出账号")
        self._window._on_kugou_login_changed()
        self.refresh_account()

    def _on_quality_changed(self) -> None:
        quality = str(self._quality.currentData() or "")
        if quality:
            self.quality_changed.emit(quality)

    def _on_device_changed(self) -> None:
        device_id = str(self._device.currentData() or "")
        if device_id:
            self.output_device_changed.emit(device_id)
