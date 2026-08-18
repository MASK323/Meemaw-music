"""Main-window animation layer.

The original MainWindow still owns every page, player overlay, queue, lyrics,
comments, and navigation callback.  Only the page switch is replaced: it uses
one wall-clock-driven fade, never combines a geometry slide with an opacity
effect, and safely tears down the previous animation before starting a new
one.  The player page keeps the original "pull up / pull down" snapshot
overlay animation (860 ms enter / 840 ms exit with an ease-in-out-quad curve)
so opening and closing the player feels identical to the reference build.
"""
from __future__ import annotations

from app.ui._main_window_original import *  # noqa: F401,F403
from app.ui._main_window_original import MainWindow as _OriginalMainWindow
from app.ui import _main_window_original as _original_main_window
from app.ui.pages import SettingsPage, KugouPage
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect

# The frozen original module stores imported page classes in its own globals.
# Rebind these explicitly so its constructor always creates the extended pages.
_original_main_window.SettingsPage = SettingsPage
_original_main_window.KugouPage = KugouPage


class MainWindow(_OriginalMainWindow):
    """Original main window with stable, rounded-surface-friendly transitions."""

    _REGULAR_PAGE_TRANSITION_MS = 230
    _PLAYER_ENTER_MS = 860
    _PLAYER_EXIT_MS = 840

    def __init__(self):
        super().__init__()
        self._combos_fitted = False
        try:
            from app.ui.widgets import fit_all_combo_popups
            from app.core.theme_manager import get_theme_manager

            def _fit_later():
                fit_all_combo_popups(self)
                self._combos_fitted = True

            QTimer.singleShot(0, _fit_later)
            QTimer.singleShot(120, _fit_later)
            try:
                get_theme_manager().theme_changed.connect(
                    lambda _theme_id: QTimer.singleShot(
                        0, lambda: fit_all_combo_popups(self)
                    )
                )
            except Exception:
                pass
        except Exception:
            pass

    def _animate_page_switch(self, index):  # noqa: N802 - Qt API
        """Dispatch a page switch with working player enter/exit branches.

        This keeps the original interruption protocol (stop the old timer,
        run the old finish, re-read the current widget) and routes the
        now-playing page through the dedicated snapshot enter/exit animations.
        """
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
        if page is self.now_playing_page:
            self._animate_player_enter(index, current)
        elif current is self.now_playing_page:
            self._animate_player_exit(index, page)
        else:
            self._animate_regular_switch(index, current, page)

    def _animate_regular_switch(self, index, current, page):  # noqa: N802 - Qt API
        """Fade a page in without moving its layout while it is being painted.

        A single opacity transition is cheaper and steadier than the old
        opacity+slide combination, works for every page, and leaves cover /
        lyrics / image / comment widgets in their original layout.
        """
        stack = self._stack
        # Commit the layout with updates disabled so no half-painted frame
        # can appear while the sidebar/player decorations change.
        stack.setUpdatesEnabled(False)
        try:
            if current is not None and current is not page:
                if current is self.now_playing_page:
                    self._set_player_mode(False)
                current.setGraphicsEffect(None)
                current.move(0, 0)
            stack.setCurrentIndex(index)
            page.setGraphicsEffect(None)
            page.move(0, 0)
            page.show()
        finally:
            stack.setUpdatesEnabled(True)
        self.root_layout.activate()
        self.repaint()

        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)

        animation = None

        def finish():
            # _animate_page_switch() calls the previous finish callback after
            # clearing _page_animation when navigation is interrupted.  The
            # cleanup must therefore be unconditional or an old opacity
            # effect can remain attached to a page forever.
            self._page_animation = None
            self._page_finish = None
            page.setGraphicsEffect(None)
            page.move(0, 0)
            page.show()

        def step(progress: float):
            # Clamp because a delayed Windows timer can report a final value
            # slightly outside the expected interval.
            value = max(0.0, min(1.0, float(progress)))
            effect.setOpacity(value)

        self._page_finish = finish
        animation = self._start_transition(
            self._REGULAR_PAGE_TRANSITION_MS,
            self._ease_out_cubic,
            step,
            self._on_page_switch_finished,
        )
        self._page_animation = animation

    def _hide_player_overlay(self) -> None:
        """Retire the snapshot overlay and its live widget references."""
        overlay = getattr(self, "_player_overlay", None)
        if overlay is not None:
            try:
                overlay.set_live_widgets(None, None)
                overlay.hide()
            except RuntimeError:
                pass

    @staticmethod
    def _reset_page_geometry(stack, page) -> None:
        if page is None:
            return
        page.setGraphicsEffect(None)
        page.setGeometry(stack.rect())
        page.move(0, 0)
        page.show()
        page.raise_()

    def _animate_player_enter(self, index, current):  # noqa: N802 - Qt API
        """Pull the player page up with the original snapshot overlay.

        The old page is captured, blurred and faded underneath while the
        player page slides upward; live page/top-bar/player-bar widgets are
        composited on top.  This is the reference build''s enter animation.
        """
        page = self.now_playing_page
        overlay = self._player_overlay
        current_index = self._stack.indexOf(current)
        if current is not None:
            current.setGraphicsEffect(None)
            current.setGeometry(self._stack.rect())
            current.move(0, 0)
            current.show()
            current.raise_()
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
            background, None,
            bg_blur=background_blur, entry_rect=entry_rect,
            entry_pixmap=bar_pixmap,
        )
        parent = overlay.parentWidget()
        overlay.setGeometry(parent.rect() if parent is not None else self.rect())
        overlay.set_progress(0.0)
        overlay.set_blur(0.8)
        overlay.set_fade(1.0)
        overlay.show()
        overlay.raise_()
        overlay.repaint()
        QApplication.processEvents()
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

        def _on_enter_progress(value):
            p = max(0.0, min(1.0, float(value)))
            overlay.set_progress(p)
            overlay.set_blur(0.8 * (1.0 - p))

        def _end_enter():
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
            self._PLAYER_ENTER_MS,
            self._ease_in_out_quad,
            _on_enter_progress,
            self._on_page_switch_finished,
        )

    def _animate_player_exit(self, index, target):  # noqa: N802 - Qt API
        """Drop the player page back down with the original snapshot overlay.

        The target page is prepared underneath while a live snapshot of the
        player (with its blurred background) shrinks back down to the player
        bar.  This is the reference build''s exit animation.
        """
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
        overlay.set_live_widgets(page, self.top_bar, self.player_bar)
        overlay.set_content(None, None)
        parent = overlay.parentWidget()
        overlay.setGeometry(parent.rect() if parent is not None else self.rect())
        overlay.set_progress(1.0)
        overlay.set_blur(0.0)
        overlay.set_fade(1.0)
        overlay.show()
        overlay.raise_()
        overlay.repaint()
        QApplication.processEvents()
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
            main_pixmap, None,
            bg_blur=main_blur, entry_rect=entry_rect,
            entry_pixmap=bar_pixmap,
        )
        overlay.set_live_widgets(page, self.top_bar, self.player_bar)
        overlay._refresh_live_cache()
        self._set_transition_mode(page, True)
        overlay.set_progress(1.0)
        overlay.set_blur(0.0)
        overlay.set_fade(1.0)

        def _on_exit_progress(value):
            p = max(0.0, min(1.0, float(value)))
            overlay.set_progress(1.0 - p)
            overlay.set_blur(0.0)

        def _end_exit():
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
            overlay.set_content(
                main_pixmap, None,
                entry_rect=entry_rect, entry_pixmap=bar_pixmap,
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
            self._PLAYER_EXIT_MS,
            self._ease_in_out_quad,
            _on_exit_progress,
            self._on_page_switch_finished,
        )


__all__ = [name for name in globals() if not name.startswith("_")]
