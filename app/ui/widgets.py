"""Meemaw widget compatibility layer with a compact playback-speed control.

The original widgets module stays intact under ``app.ui._widgets_original``.
Only PlayerBar is subclassed, so cover, lyric, comment, queue, like, seek,
volume, and play-mode controls continue to use the original implementation.
"""
from __future__ import annotations

from app.ui._widgets_original import *  # noqa: F401,F403
from app.ui import _widgets_original as _original_widgets
from app.ui._widgets_original import (
    PlayerBar as _OriginalPlayerBar,
    LyricView as _OriginalLyricView,
)
from app.core.theme_manager import get_theme_manager
from PySide6.QtCore import QEvent, QTimer, Qt, Signal, QObject, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QLinearGradient, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QStyledItemDelegate,
    QStyle, QStyleOptionViewItem, QWidget,
)


def _glass_gradient(rect):
    """Shared light glass band used for popup hover and selected options."""
    gloss = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gloss.setColorAt(0.00, QColor(255, 255, 255, 42))
    gloss.setColorAt(0.32, QColor(255, 255, 255, 16))
    gloss.setColorAt(0.46, QColor(255, 255, 255, 82))
    gloss.setColorAt(0.54, QColor(255, 255, 255, 20))
    gloss.setColorAt(1.00, QColor(255, 255, 255, 34))
    return gloss


class _RoundedPopupDelegate(QStyledItemDelegate):

    """Paint hover/selection surfaces explicitly instead of relying on QSS.

    Qt recreates a combo popup and its style object on every open.  On some
    Windows style combinations the stylesheet ``:hover`` state then remains
    stale after the second or third open.  Painting the small rounded surface
    in the delegate keeps the visual state deterministic.
    """

    def __init__(self, parent, background, hover, border, combo=None):
        super().__init__(parent)
        self._background = QColor(background)
        self._hover = QColor(hover) if not hover.startswith("rgba") else QColor(255, 255, 255, 26)
        self._border = QColor(border)
        self._hovered_row = -1
        self._combo = combo

    def set_hovered_row(self, row: int) -> None:
        row = int(row)
        if row == self._hovered_row:
            return
        self._hovered_row = row
        view = self.parent()
        try:
            if view is not None:
                view.viewport().update()
        except RuntimeError:
            pass

    def sizeHint(self, option, index):  # noqa: N802 - Qt API
        size = super().sizeHint(option, index)
        # Keep rows compact; hover margins are painted, not added to geometry.
        size.setHeight(34)
        return size

    def paint(self, painter, option, index):  # noqa: N802 - Qt API
        opt = QStyleOptionViewItem(option)
        hovered = (
            bool(option.state & QStyle.StateFlag.State_MouseOver)
            or index.row() == self._hovered_row
        )
        # A combo popup does not reliably mark its current item with
        # State_Selected on every Windows style, so also treat the combo's
        # current row as selected.  This keeps a visible "which one is active"
        # hint whenever the dropdown opens.
        combo = getattr(self, "_combo", None)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if not selected and combo is not None:
            try:
                current = combo.currentIndex()
                selected = current >= 0 and index.row() == current
            except RuntimeError:
                selected = False
        if hovered or selected:
            rect = option.rect.adjusted(3, 2, -3, -2)
            path = QPainterPath()
            path.addRoundedRect(rect, 8.0, 8.0)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if selected:
                # Solid accent + a light mirror gloss: the selected option is
                # unmistakable and still matches the rounded glass language.
                painter.fillPath(path, QColor("#ec4141"))
                gloss = _glass_gradient(rect)
                painter.fillPath(path, gloss)
            else:
                # A narrow light band over a translucent local surface gives
                # the option a glass/mirror highlight without introducing a
                # dark outline.  The delegate paints this explicitly because
                # Qt's popup stylesheet hover state is unreliable on Windows.
                painter.fillPath(path, _glass_gradient(rect))
            painter.restore()
            opt.state &= ~QStyle.StateFlag.State_MouseOver
            opt.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, opt, index)


def _set_popup_hover(view, delegate, event=None) -> None:
    """Paint hover from the actual pointer position, not only Qt's style flag."""
    try:
        if event is not None and event.type() == QEvent.Type.Leave:
            row = -1
        else:
            point = view.viewport().mapFromGlobal(QCursor.pos())
            index = view.indexAt(point)
            row = index.row() if index.isValid() else -1
        if delegate is not None:
            delegate.set_hovered_row(row)
    except (RuntimeError, AttributeError):
        pass


class _PopupEventFilter(QObject):
    """Refresh combo popup hover state whenever Qt sends a popup event."""

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if event.type() in (
            QEvent.Type.Show,
            QEvent.Type.WindowActivate,
            QEvent.Type.Enter,
            QEvent.Type.MouseMove,
            QEvent.Type.Leave,
        ):
            update_hover = getattr(self._owner, "_update_popup_hover", None)
            if callable(update_hover):
                update_hover(event)
            else:
                view_getter = getattr(self._owner, "view", None)
                delegate = getattr(self._owner, "_popup_delegate", None)
                if callable(view_getter):
                    _set_popup_hover(view_getter(), delegate, event)
            refresh = getattr(self._owner, "_schedule_popup_refresh", None)
            if callable(refresh):
                refresh()
        return False


class _TitleOnlyRowDelegate(QStyledItemDelegate):
    """Keep row clicks, but paint selection on the title cell only.

    The original delegate paints a rounded rectangle from the first column to
    the complete viewport width.  That makes a song selection look like the
    whole row is selected.  The table remains row-selectable for playback and
    double-click handling; only the title cell receives the selected surface.
    """

    def __init__(self, view=None, parent=None):
        super().__init__(parent)
        self._view = view

    def paint(self, painter, option, index):  # noqa: N802 - Qt API
        opt = QStyleOptionViewItem(option)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if selected:
            # Only column 1 is the song title.  Clear the selection state for
            # every other cell so Qt cannot paint a full-row highlight.
            opt.state &= ~QStyle.StateFlag.State_Selected
            if index.column() == 1:
                rect = option.rect.adjusted(3, 2, -3, -2)
                path = QPainterPath()
                path.addRoundedRect(rect, 10.0, 10.0)
                painter.fillPath(path, QColor(236, 65, 65, 42))
        elif hovered and index.column() == 0:
            # Preserve the original quiet row-hover treatment across the row;
            # selection itself is intentionally title-only.
            try:
                viewport = self._view.viewport() if self._view is not None else None
                width = viewport.width() if viewport is not None else option.rect.width()
            except RuntimeError:
                width = option.rect.width()
            row_rect = QRectF(4, option.rect.top() + 3, max(0, width - 8), max(0, option.rect.height() - 6))
            path = QPainterPath()
            path.addRoundedRect(row_rect, 14.0, 14.0)
            painter.fillPath(path, QColor(255, 255, 255, 13))
        painter.restore()
        super().paint(painter, opt, index)


# SongTable is defined in the frozen original module and looks up its delegate
# through that module's globals. Rebind only the delegate so all table data,
# columns, row clicks and playback callbacks remain untouched.
_original_widgets.RoundedRowDelegate = _TitleOnlyRowDelegate
RoundedRowDelegate = _TitleOnlyRowDelegate


def fit_all_combo_popups(root) -> None:
    """Apply the rounded surface-matching popup to every combo under root.

    Plain QComboBox instances (settings quality/device, playlist provider,
    chart selector, player quality) all receive the same delegate so hover
    shows the glass mirror and the current item shows a clear accent
    selection.  Speed selectors keep their own _SpeedCombo implementation.
    """
    if root is None:
        return
    try:
        combos = root.findChildren(QComboBox)
    except RuntimeError:
        return
    for combo in combos:
        try:
            if combo is None:
                continue
            # _SpeedCombo manages its own popup styling.
            if hasattr(combo, "_prepare_popup"):
                continue
            if getattr(combo, "_popup_delegate", None) is not None and hasattr(combo, "_popup_filter"):
                continue
            _fit_option_combo_popup(combo)
        except (RuntimeError, AttributeError, TypeError, ValueError):
            continue


def _fit_option_combo_popup(combo: QComboBox) -> None:
    """Fit a fixed-option combo popup and give it the same glass hover surface."""
    if combo is None:
        return
    try:
        view = combo.view()
        model = view.model()
        count = model.rowCount() if model is not None else 0
        if count <= 0:
            return
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setLineWidth(0)
        view.setMidLineWidth(0)
        view.setContentsMargins(0, 0, 0, 0)
        view.setViewportMargins(0, 0, 0, 0)
        view.setMouseTracking(True)
        view.viewport().setMouseTracking(True)
        view.setUniformItemSizes(True)
        view.setSpacing(0)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        theme = get_theme_manager().current()
        # Match the popup to the surface it opens over.  A combo inside a
        # settings card shares the card colour, the player-bar combo shares
        # the translucent bar surface, the now-playing quality combo shares
        # that page's dark surface and any regular page shares that page's
        # canvas.  Never fall back to the generic popup colour here or the
        # dropdown visibly disagrees with its surroundings.
        ancestor = combo.parentWidget()
        surface = "page"
        while ancestor is not None:
            name = ancestor.objectName() or ""
            if name == "settingsCard":
                surface = "card"
                break
            if name == "playerBar":
                surface = "playerBar"
                break
            if name == "nowPlayingPage":
                surface = "nowPlaying"
                break
            class_name = type(ancestor).__name__
            if class_name in ("LegacyChartsPage", "KugouPage", "ChartsPage"):
                surface = "page"
                break
            if class_name in ("SettingsPage",):
                surface = "page"
                break
            ancestor = ancestor.parentWidget()
        if surface == "playerBar":
            background = "#211e1c"
        elif surface == "nowPlaying":
            background = "#343434"
        elif surface == "card":
            background = theme.card
        else:
            background = theme.page
        text = "#e8e8ec" if surface in ("playerBar", "nowPlaying") else theme.text
        if not hasattr(combo, "_popup_filter"):
            combo._popup_filter = _PopupEventFilter(combo)
        delegate = getattr(combo, "_popup_delegate", None)
        if delegate is None:
            delegate = _RoundedPopupDelegate(view, background, theme.hover, theme.border_strong, combo)
            combo._popup_delegate = delegate
            view.setItemDelegate(delegate)
        else:
            # Re-fitting after a theme change refreshes the painted colours.
            try:
                delegate._background = QColor(background)
                delegate._hover = QColor(theme.hover) if not theme.hover.startswith("rgba") else QColor(255, 255, 255, 26)
                delegate._combo = combo
            except Exception:
                pass
        for watched in (view.window(), view, view.viewport()):
            if watched is not None and not watched.property("meemawPopupFilter"):
                watched.installEventFilter(combo._popup_filter)
                watched.setProperty("meemawPopupFilter", True)
        accent = "#ec4141" if surface in ("playerBar", "nowPlaying") else theme.accent
        style = (
            f"QAbstractItemView {{ color: {text}; background: {background}; border: none; "
            "border-radius: 14px; outline: none; padding: 4px; margin: 0; "
            "selection-background-color: " + accent + "; selection-color: #ffffff; }"
            "QAbstractItemView::item { color: " + text + "; background: transparent; "
            "border: none; border-radius: 8px; padding: 0 10px; margin: 0; }"
            "QAbstractItemView::item:hover { background: transparent; border: none; }"
            "QAbstractItemView::item:selected { background: " + accent + "; border: none; }"
            "QComboBoxPrivateContainer { background: " + background + "; border: none; }"
            "QListView { background: " + background + "; border: none; }"
        )
        view.setStyleSheet(style)
        popup = view.window()
        if popup is not None:
            popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            popup.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
            popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            popup.setContentsMargins(0, 0, 0, 0)
            popup.setAutoFillBackground(False)
            popup.setStyleSheet(style)
        delegate.set_hovered_row(-1)
        row_height = max(30, view.sizeHintForRow(0) or 0)
        height = row_height * count + 8
        metrics = view.fontMetrics()
        widest = max(
            metrics.horizontalAdvance(str(model.data(model.index(row, 0)) or ""))
            for row in range(count)
        )
        width = max(combo.width(), min(360, max(120, widest + 34)))
        if popup is not None:
            popup.setFixedSize(int(width), int(height))
        view.setFixedSize(int(width), int(height))
    except (RuntimeError, AttributeError, TypeError, ValueError):
        pass


class _SmoothLyricView(_OriginalLyricView):
    """Keep the original lyric renderer but coalesce high-rate position ticks.

    The player sends progress updates more often than a lyric line can change.
    Forwarding every tick to a custom-painted view causes repeated target
    calculations and fractional repaint positions, which is perceived as
    lyric jitter.  A single 60 Hz pending timer gives the view one monotonic
    position per frame while retaining the original centered lyric layout and
    seek behavior.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending_position_ms = None
        self._applied_position_ms = None
        self._position_flush = QTimer(self)
        self._position_flush.setSingleShot(True)
        self._position_flush.setInterval(16)
        self._position_flush.timeout.connect(self._flush_position)
        # A slightly longer scroll settle time avoids the original timer's
        # visible micro-steps when a line boundary is crossed.
        self._scroll_settle_timer = QTimer(self)
        self._scroll_settle_timer.setInterval(16)
        self._scroll_settle_timer.timeout.connect(self._smooth_scroll_tick)

    def set_position(self, position_ms: int) -> None:  # noqa: N802 - Qt API
        try:
            value = max(0, int(position_ms))
        except (TypeError, ValueError):
            return
        previous = self._pending_position_ms
        self._pending_position_ms = value
        if previous is not None and abs(value - previous) < 4:
            return
        if not self._position_flush.isActive():
            self._position_flush.start()

    def _flush_position(self) -> None:
        value = self._pending_position_ms
        if value is None:
            return
        if self._applied_position_ms is not None and value == self._applied_position_ms:
            return
        self._applied_position_ms = value
        super().set_position(value)
        # The original method starts its own 16 ms timer when the active row
        # changes. Stop it before using the smoother driver below; two timers
        # writing the same fractional scroll value are the main source of
        # visible lyric tremor.
        original_timer = getattr(self, "_anim_timer", None)
        if original_timer is not None and original_timer.isActive():
            original_timer.stop()
        if bool(getattr(self, "_manual_scrolling", False)):
            # A manual wheel animation is in progress; it owns _scroll until
            # it finishes, so never fight it with the settle driver.
            self._scroll_settle_timer.stop()
            return
        target = float(getattr(self, "_scroll_target", getattr(self, "_scroll", 0.0)))
        current = float(getattr(self, "_scroll", target))
        if abs(target - current) > 0.25 and not self._scroll_settle_timer.isActive():
            self._scroll_settle_timer.start()

    def _smooth_scroll_tick(self) -> None:
        # The original row-change path may start its own 16 ms _anim_timer
        # (for example a resize re-centre during the player pull-up).  Two
        # timers writing the same scroll value are the main source of lyric
        # tremor and of the live-composited flicker, so the original timer is
        # stopped before every smooth tick.
        original_timer = getattr(self, "_anim_timer", None)
        if original_timer is not None and original_timer.isActive():
            original_timer.stop()
        if bool(getattr(self, "_manual_scrolling", False)):
            # A manual wheel animation is in progress; it owns _scroll until
            # it finishes.
            self._scroll_settle_timer.stop()
            return
        target = float(getattr(self, "_scroll_target", 0.0))
        current = float(getattr(self, "_scroll", target))
        delta = target - current
        if abs(delta) <= 0.5:
            self._scroll = target
            self._scroll_settle_timer.stop()
        else:
            self._scroll = current + delta * 0.16
            if abs(target - float(self._scroll)) <= 0.5:
                self._scroll = target
                self._scroll_settle_timer.stop()
        if not bool(getattr(self, "_transition_suppress_paint", False)):
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Any paint that still reaches the renderer with a fractional scroll
        # (seek, theme relayout, resize re-centre) is snapped to a whole
        # pixel so lyric text never shimmers between frames.
        scroll = getattr(self, "_scroll", 0.0)
        if isinstance(scroll, float) and not scroll.is_integer():
            self._scroll = round(scroll)
        super().paintEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Manual wheel motion has its own QVariantAnimation. Never let it run
        # concurrently with the lyric-line settle driver.
        self._scroll_settle_timer.stop()
        delta = event.angleDelta().y()
        if delta:
            self._time_visible = True
            self._time_hide_timer.start()
            self._manual_scrolling = True
            max_scroll = max(0, self._content_height() - self.height())
            target = min(
                max(0.0, float(self._scroll) - delta * 0.35), float(max_scroll)
            )
            anim = self._wheel_anim
            anim.stop()
            # The patch keeps _scroll as an int between frames. QVariantAnimation
            # requires start/end of the same type, and int -> float silently
            # produces no valueChanged, which freezes manual scrolling. Force
            # the start value to float so the wheel animation actually runs.
            anim.setStartValue(float(self._scroll))
            anim.setEndValue(target)
            anim.start()
        event.accept()

    def set_lines(self, lines) -> None:  # noqa: N802 - Qt API
        self._position_flush.stop()
        self._scroll_settle_timer.stop()
        self._pending_position_ms = None
        self._applied_position_ms = None
        super().set_lines(lines)

    def set_transition_mode(self, active: bool) -> None:  # noqa: N802 - Qt API
        super().set_transition_mode(active)
        if (
            not active
            and not bool(getattr(self, "_manual_scrolling", False))
            and abs(
                float(getattr(self, "_scroll_target", 0.0))
                - float(getattr(self, "_scroll", 0.0))
            ) > 0.25
            and not self._scroll_settle_timer.isActive()
        ):
            self._scroll_settle_timer.start()


# LyricsPanel in the original module resolves LyricView through its own
# module globals. Replace that binding before any page constructs a panel.
_original_widgets.LyricView = _SmoothLyricView
LyricView = _SmoothLyricView


class _SpeedCombo(QComboBox):
    """A speed selector with a rounded popup matching its local surface."""

    def __init__(
        self,
        parent=None,
        popup_background="#211e1c",
        control_background="transparent",
        hover_background="rgba(255, 255, 255, 0.08)",
        border_color="#51463d",
    ):
        super().__init__(parent)
        self._popup_background = popup_background
        self._control_background = control_background
        self._hover_background = hover_background
        self._border_color = border_color
        self._popup_filter = _PopupEventFilter(self)
        self._popup_delegate = None
        self._popup_refresh_pending = False

    def _style(self) -> str:
        theme = get_theme_manager().current()
        # The speed selector lives inside the player. Keep its original dark
        # player treatment even when the rest of the application uses the
        # EchoMusic light skin; global skin changes must not repaint player UI.
        player_control = self.objectName() in {"playbackSpeed", "nowPlayingPlaybackSpeed"}
        text_color = "#ffffff" if player_control else theme.text
        accent_color = "#ec4141" if player_control else theme.accent
        accent_hover = "#ff6666" if player_control else theme.accent_hover
        style = (
            "QComboBox { color: #ffffff; background: %s; border: none; "
            "border-radius: 12px; outline: none; padding: 0 6px; font-size: 12px; }"
            "QComboBox:hover { color: #ff6666; background: "
            "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "stop:0 rgba(255,255,255,0.16), stop:0.45 rgba(255,255,255,0.06), "
            "stop:0.52 rgba(255,255,255,0.24), stop:1 rgba(255,255,255,0.12)); "
            "border: none; }"
            "QComboBox:focus { border: none; outline: none; }"
            "QComboBox::drop-down { border: none; width: 14px; background: transparent; }"
            "QComboBox::down-arrow { width: 0px; height: 0px; border: none; }"
            "QComboBoxPrivateContainer { background: transparent; border: none; }"
            "QComboBoxPrivateContainer { background: %s; border: none; border-radius: 14px; }"
            "QAbstractItemView, QListView { color: #ffffff; background: %s; "
            "border: none; border-radius: 14px; outline: none; "
            "padding: 4px; margin: 0px; selection-background-color: #ec4141; "
            "selection-color: #ffffff; }"
            "QAbstractItemView::item, QListView::item { color: #ffffff; "
            "background: transparent; padding: 0 10px; margin: 0; "
            "border: none; border-radius: 8px; }"
            "QAbstractItemView::item:hover, QListView::item:hover { "
            "color: #ffffff; background: "
            "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "stop:0 rgba(255,255,255,0.16), stop:0.45 rgba(255,255,255,0.06), "
            "stop:0.52 rgba(255,255,255,0.24), stop:1 rgba(255,255,255,0.12)); "
            "border: none; }"
            "QAbstractItemView::item:selected, QListView::item:selected { "
            "color: #ffffff; background: #ec4141; border: none; }"
            "QListView { background: %s; border: none; }"
        ) % (
            self._control_background,
            self._popup_background,
            self._popup_background,
            self._popup_background,
        )
        return (
            style.replace("#ffffff", text_color)
            .replace("#ec4141", accent_color)
            .replace("#ff6666", accent_hover)
        )

    def _refresh_theme(self) -> None:
        theme = get_theme_manager().current()
        if self.objectName() == "nowPlayingPlaybackSpeed":
            self._popup_background = "#343434"
            self._hover_background = "#403b38"
            self._border_color = "#57493f"
        elif self.objectName() == "playbackSpeed":
            self._popup_background = "#211e1c"
            self._hover_background = "#332b26"
            self._border_color = "#57493f"
        else:
            self._popup_background = theme.popup
            self._hover_background = theme.hover
            self._border_color = theme.border_strong
        self._popup_delegate = None
        self.setStyleSheet(self._style())
        self._prepare_popup()

    def _prepare_popup(self) -> None:
        view = self.view()
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setLineWidth(0)
        view.setMidLineWidth(0)
        view.setContentsMargins(0, 0, 0, 0)
        view.setViewportMargins(0, 0, 0, 0)
        view.setMouseTracking(True)
        view.viewport().setMouseTracking(True)
        view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        if self._popup_delegate is None:
            self._popup_delegate = _RoundedPopupDelegate(
                view, self._popup_background, self._hover_background, self._border_color, self
            )
            view.setItemDelegate(self._popup_delegate)

        popup = view.window()
        if popup is None:
            return
        popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        popup.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        popup.setContentsMargins(0, 0, 0, 0)
        popup.setAutoFillBackground(False)
        for watched in (popup, view, view.viewport()):
            if watched is not None and not watched.property("meemawPopupFilter"):
                watched.installEventFilter(self._popup_filter)
                watched.setProperty("meemawPopupFilter", True)
        style = self._style()
        if view.styleSheet() != style:
            view.setStyleSheet(style)
        if popup.styleSheet() != style:
            popup.setStyleSheet(style)
        self._fit_popup()

    def _fit_popup(self) -> None:
        """Size the transient window to its rows instead of native minimums."""
        try:
            view = self.view()
            model = view.model()
            count = model.rowCount() if model is not None else 0
            if count <= 0:
                return
            view.setUniformItemSizes(True)
            view.setSpacing(0)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            # These selectors contain only a handful of fixed options.  Show
            # the complete list in one rounded popup instead of creating an
            # unnecessary scrollbar inside the option box.
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            row_height = 34
            height = row_height * count + 8
            metrics = view.fontMetrics()
            widest = 0
            for row in range(count):
                widest = max(widest, metrics.horizontalAdvance(str(model.data(model.index(row, 0)) or "")))
            width = max(self.width(), min(360, max(120, widest + 34)))
            popup = view.window()
            if popup is not None:
                popup.setFixedSize(int(width), int(height))
            view.setFixedSize(int(width), int(height))
            view.updateGeometry()
        except (RuntimeError, AttributeError, TypeError):
            pass

    def _update_popup_hover(self, event=None) -> None:
        """Track the item under the pointer even when Qt omits State_MouseOver."""
        _set_popup_hover(self.view(), self._popup_delegate, event)

    def _schedule_popup_refresh(self) -> None:
        if self._popup_refresh_pending:
            return
        self._popup_refresh_pending = True

        def refresh():
            self._popup_refresh_pending = False
            try:
                view = self.view()
                view.setMouseTracking(True)
                view.viewport().setMouseTracking(True)
                view.update()
                view.viewport().update()
                self._fit_popup()
                if view.window() is not None:
                    view.window().update()
            except RuntimeError:
                pass

        QTimer.singleShot(0, refresh)
        QTimer.singleShot(32, refresh)

    def showPopup(self) -> None:  # noqa: N802 - Qt API name
        # Apply flags before Qt lays out the transient window.  Reapplying
        # styles after show used to make repeated opens lose hover painting.
        self._prepare_popup()
        if self._popup_delegate is not None:
            self._popup_delegate.set_hovered_row(-1)
        super().showPopup()
        self._prepare_popup()
        self._fit_popup()
        self._schedule_popup_refresh()


class PlayerBar(_OriginalPlayerBar):
    """Original player bar plus selectable HTML-audio playback rate controls."""

    playback_rate_changed = Signal(float)
    PLAYBACK_RATES = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)

    def __init__(self, image_loader, parent=None):
        super().__init__(image_loader, parent)
        self._playback_rate = 1.0
        get_theme_manager().theme_changed.connect(self._on_theme_changed)

        combo = self._make_speed_combo(self, "playbackSpeed")
        self._speed_combo = combo
        combo.currentIndexChanged.connect(self._on_speed_selected)

        # The normal window keeps PlayerBar at the bottom. Player mode hides
        # that bar, so expose the same control on NowPlayingPage too.
        self._page_speed_combo = None
        self._page_speed_attempts = 0
        QTimer.singleShot(0, self._install_now_playing_speed)

        # Add the control to the existing row without rebuilding the original
        # layout. This preserves all existing player controls and signals.
        root_layout = self.layout()
        row = None
        if root_layout is not None:
            for index in range(root_layout.count()):
                candidate = root_layout.itemAt(index).layout()
                if candidate is None:
                    continue
                if any(
                    candidate.indexOf(widget) >= 0
                    for widget in (
                        getattr(self, "_play", None),
                        getattr(self, "_lyric", None),
                        getattr(self, "_queue", None),
                    )
                    if widget is not None
                ):
                    row = candidate
                    break
            if row is None and root_layout.count() > 1:
                row = root_layout.itemAt(1).layout()
        if row is not None:
            row.addWidget(combo)
        elif root_layout is not None:
            root_layout.addWidget(combo)

    def _on_theme_changed(self, _theme_id: str) -> None:
        for combo in (getattr(self, "_speed_combo", None), getattr(self, "_page_speed_combo", None)):
            if combo is not None and hasattr(combo, "_refresh_theme"):
                combo._refresh_theme()

    @staticmethod
    def _find_now_playing_page(window):
        page = getattr(window, "now_playing_page", None)
        if page is None and isinstance(window, QWidget):
            page = window.findChild(QWidget, "nowPlayingPage")
        return page

    def _install_now_playing_speed(self) -> None:
        if self._page_speed_combo is not None:
            return
        page_combo = None
        try:
            window = self.window()
            page = self._find_now_playing_page(window)
            if page is None:
                raise RuntimeError("NowPlayingPage is not attached yet")

            existing = page.findChild(QComboBox, "nowPlayingPlaybackSpeed")
            if existing is not None:
                page_combo = existing
            else:
                page_combo = self._make_speed_combo(page, "nowPlayingPlaybackSpeed")
                page_combo.currentIndexChanged.connect(self._on_speed_selected)
                if not self._attach_page_speed_combo(page, page_combo):
                    page_combo.deleteLater()
                    page_combo = None
                    raise RuntimeError("NowPlayingPage controls are not ready")

            self._page_speed_combo = page_combo
            quality = getattr(page, "_quality", None)
            if isinstance(quality, QComboBox):
                _fit_option_combo_popup(quality)
                # The popup window can be recreated by the native style on
                # first open, so repeat after it has had a chance to exist.
                QTimer.singleShot(0, lambda combo=quality: _fit_option_combo_popup(combo))
                QTimer.singleShot(48, lambda combo=quality: _fit_option_combo_popup(combo))
            # Give the now-playing quality combo (and any other combo on that
            # page) the same rounded mirror/accent popup treatment.
            fit_all_combo_popups(page)
            page_combo.blockSignals(True)
            page_combo.setCurrentIndex(self._speed_combo.currentIndex())
            page_combo.blockSignals(False)
        except Exception:
            if page_combo is not None and page_combo is not self._page_speed_combo:
                page_combo.deleteLater()
            self._page_speed_attempts += 1
            # PlayerBar is constructed before MainWindow finishes assembling
            # the page. Retry briefly without delaying application startup.
            if self._page_speed_attempts < 50:
                QTimer.singleShot(100, self._install_now_playing_speed)

    @classmethod
    def _make_speed_combo(cls, parent, object_name: str) -> QComboBox:
        theme = get_theme_manager().current()
        if object_name == "nowPlayingPlaybackSpeed":
            background, hover, border = "#343434", "#403b38", "#57493f"
        elif object_name == "playbackSpeed":
            background, hover, border = "#211e1c", "#332b26", "#57493f"
        else:
            background, hover, border = theme.page, theme.hover, theme.border_strong
        combo = _SpeedCombo(parent, background, "transparent", hover, border)
        combo.setObjectName(object_name)
        combo.setToolTip("\u64ad\u653e\u901f\u5ea6")
        combo.setFixedSize(62, 28)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        combo.setStyleSheet(combo._style())
        for rate in cls.PLAYBACK_RATES:
            combo.addItem(cls._format_rate(rate), rate)
        combo.setCurrentIndex(cls.PLAYBACK_RATES.index(1.0))
        combo._prepare_popup()
        return combo

    @staticmethod
    def _find_layout_with_widgets(layout, widgets):
        if layout is None:
            return None
        if any(widget is not None and layout.indexOf(widget) >= 0 for widget in widgets):
            return layout
        for index in range(layout.count()):
            item = layout.itemAt(index)
            child = item.layout()
            if child is None:
                widget = item.widget()
                child = widget.layout() if widget is not None else None
            found = PlayerBar._find_layout_with_widgets(child, widgets)
            if found is not None:
                return found
        return None

    @classmethod
    def _attach_page_speed_combo(cls, page, combo) -> bool:
        # NowPlayingPage keeps quality and volume in a nested control row.
        # Insert speed immediately after quality, preserving that page's
        # cover/lyrics/image/comment UI and all original controls.
        row = cls._find_layout_with_widgets(
            page.layout(),
            (getattr(page, "_quality", None), getattr(page, "_volume", None)),
        )
        if row is None:
            return False
        quality = getattr(page, "_quality", None)
        position = row.indexOf(quality) if quality is not None else -1
        if position >= 0:
            row.insertWidget(position + 1, combo)
        else:
            row.addWidget(combo)
        return True

    @staticmethod
    def _format_rate(rate: float) -> str:
        return f"{rate:g}\u00d7"

    def _on_speed_selected(self, index: int) -> None:
        if index < 0:
            return
        data = self._speed_combo.itemData(index)
        try:
            value = float(data)
        except (TypeError, ValueError):
            return
        self.set_playback_rate(value)

    def _find_player(self):
        """Get MainWindow.player without coupling the original widget module."""
        try:
            return getattr(self.window(), "player", None)
        except Exception:
            return None

    def set_playback_rate(self, rate: float) -> None:
        try:
            value = float(rate)
        except (TypeError, ValueError):
            return
        value = min(self.PLAYBACK_RATES, key=lambda item: abs(item - value))
        self._playback_rate = value

        index = self.PLAYBACK_RATES.index(value)
        for combo in (self._speed_combo, self._page_speed_combo):
            if combo is not None and combo.currentIndex() != index:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)

        player = self._find_player()
        setter = getattr(player, "set_playback_rate", None)
        if callable(setter):
            try:
                setter(value)
            except Exception:
                # The UI remains usable before the player is initialized.
                pass
        self.playback_rate_changed.emit(value)

    def playback_rate(self) -> float:
        return self._playback_rate


__all__ = [name for name in globals() if not name.startswith("_")]










