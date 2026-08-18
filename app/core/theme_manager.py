"""Small, persistent skin system for the desktop UI.

EchoMusic's theme model is deliberately simple: surfaces are layered (page,
card, elevated/popup and player), while the accent is independent.  The
original Meemaw stylesheet predates that model and contains literal colours,
so this module keeps the original selectors and remaps their palette instead
of replacing any page implementation.  That is important for the cover,
lyrics, images, comments and queue widgets which still come from the original
application.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    page: str
    sidebar: str
    card: str
    elevated: str
    panel: str
    popup: str
    player: str
    text: str
    muted: str
    border: str
    border_strong: str
    hover: str
    selected: str
    accent: str
    accent_hover: str
    accent_soft: str


THEMES: tuple[Theme, ...] = (
    Theme("dark_red", "暗夜红（默认）", "#211e1c", "#191613", "#2b2622", "#322b27", "#26211d", "#2f2925", "#343434", "#f7f7f8", "#a6a0a0", "#3a332d", "#57493f", "#332b26", "#382f2a", "#ec4141", "#ff655e", "#4a2424"),
    Theme("dark_purple", "暮色紫", "#1e1b24", "#17141d", "#292430", "#332d3b", "#25212d", "#302a38", "#302c3a", "#f6f3fb", "#aaa2b5", "#3d3548", "#635573", "#393044", "#40364e", "#a875ff", "#bd94ff", "#422b60"),
    Theme("ocean_blue", "深海蓝", "#17212b", "#111a22", "#202e3b", "#293b4b", "#1c2a36", "#243644", "#273b4b", "#eef7ff", "#9eb2c2", "#314554", "#4c687b", "#293d4d", "#2c465a", "#3f9cff", "#69b3ff", "#173f66"),
    Theme("graphite", "石墨灰", "#202225", "#18191c", "#2b2d31", "#35373c", "#25272b", "#303238", "#303238", "#f2f3f5", "#a7abb3", "#3b3e45", "#5c606a", "#363941", "#3d4049", "#8b9cff", "#a8b4ff", "#303866"),
    Theme("light", "晨雾浅色", "#f5f5f7", "#ffffff", "#ffffff", "#ffffff", "#eef0f4", "#ffffff", "#343434", "#1d1d1f", "#4b5563", "#e5e5ea", "#c6ccd4", "#f0f2f5", "#e8edf5", "#0071e3", "#0077ed", "rgba(0, 113, 227, 0.12)"),
)

_THEME_BY_ID = {item.id: item for item in THEMES}
_DEFAULT_ID = "dark_red"


def _config_path() -> Path:
    override = os.environ.get("MEEMAW_CONFIG_DIR")
    if override:
        return Path(override) / "theme.json"
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "MeemawMusic" / "theme.json"
    return Path.home() / ".config" / "meemaw-music" / "theme.json"


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self, config_path: str | os.PathLike[str] | None = None) -> None:
        super().__init__()
        self._lock = threading.RLock()
        self._config_path = Path(config_path) if config_path else _config_path()
        self._theme_id = self._load_id()
        self._base_stylesheet = ""

    def _load_id(self) -> str:
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
            value = str(payload.get("theme") or "") if isinstance(payload, dict) else ""
            return value if value in _THEME_BY_ID else _DEFAULT_ID
        except (OSError, ValueError, TypeError):
            return _DEFAULT_ID

    def _save(self) -> None:
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._config_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "theme": self._theme_id}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._config_path)
        except OSError:
            pass

    def current_id(self) -> str:
        with self._lock:
            return self._theme_id

    def current(self) -> Theme:
        return _THEME_BY_ID.get(self.current_id(), _THEME_BY_ID[_DEFAULT_ID])

    def available(self) -> list[Theme]:
        return list(THEMES)

    def register_base_stylesheet(self, stylesheet: str) -> None:
        with self._lock:
            self._base_stylesheet = str(stylesheet or "")

    def stylesheet(self, theme_id: str | None = None) -> str:
        theme = _THEME_BY_ID.get(theme_id or self.current_id(), _THEME_BY_ID[_DEFAULT_ID])
        return apply_theme_palette(self._base_stylesheet, theme)

    def set_theme(self, theme_id: str, apply: bool = True) -> bool:
        theme_id = str(theme_id or "")
        if theme_id not in _THEME_BY_ID:
            return False
        with self._lock:
            changed = theme_id != self._theme_id
            self._theme_id = theme_id
            self._save()
        if apply:
            self.apply_to_application()
        if changed:
            self.theme_changed.emit(theme_id)
        return True

    def reset(self) -> None:
        self.set_theme(_DEFAULT_ID)

    def apply_to_application(self, app=None) -> None:
        app = app or QApplication.instance()
        if app is not None:
            app.setStyleSheet(self.stylesheet())


_manager: ThemeManager | None = None
_manager_lock = threading.Lock()


def get_theme_manager() -> ThemeManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ThemeManager()
        return _manager


def current_theme() -> Theme:
    return get_theme_manager().current()


def available_themes() -> list[Theme]:
    return get_theme_manager().available()


def set_theme(theme_id: str) -> bool:
    return get_theme_manager().set_theme(theme_id)


def apply_theme_palette(stylesheet: str, theme: Theme) -> str:
    """Remap the old palette and append surface rules for all pages."""
    replacements = {
        # Original Meemaw palette.
        "#211e1c": theme.page, "#191613": theme.sidebar, "#2b2622": theme.card,
        "#322b27": theme.elevated, "#26211d": theme.panel, "#2f2925": theme.popup,
        "#343434": theme.player, "#2d2823": theme.border, "#3a332d": theme.border,
        "#39322c": theme.border, "#3d3631": theme.border,
        "#4a3f37": theme.border_strong, "#4a4a4a": theme.elevated,
        "#51463d": theme.border_strong, "#57493f": theme.border_strong,
        "#5a4c42": theme.border_strong, "#332b26": theme.hover,
        "#2b2521": theme.hover, "#2a2a31": theme.hover, "#26262e": theme.hover,
        "#382f2a": theme.selected, "#3a2223": theme.selected,
        "#212127": theme.card, "#ec4141": theme.accent, "#d84a3f": theme.accent,
        "#e24a3d": theme.accent, "#ff5b52": theme.accent_hover, "#ff5b5e": theme.accent_hover,
        "#ff6666": theme.accent_hover, "#6f3a38": theme.accent_soft,
        "#8f9299": theme.muted, "#9a9da4": theme.muted, "#7d8087": theme.muted,
        "#bdb3aa": theme.muted, "#b5b8bf": theme.muted, "#bdb6b0": theme.muted,
        "#c9ccd1": theme.text, "#cfcfd6": theme.text, "#d7d7dc": theme.text,
        "#e8e8ec": theme.text, "#f2f2f5": theme.text, "#ffffff": theme.text,
    }
    result = str(stylesheet or "")
    for old, new in replacements.items():
        result = result.replace(old, new)
    result += _surface_overrides(theme)
    return result


def _surface_overrides(theme: Theme) -> str:
    """Return the EchoMusic-style surface system for non-player pages.

    EchoMusic keeps a quiet main canvas, a white/elevated sidebar, compact
    16px cards and blue semantic actions.  The original player is deliberately
    protected at the end of this stylesheet so this visual refactor cannot
    alter its cover/lyrics/transport presentation.
    """
    return f"""
/* EchoMusic layout tokens: canvas -> card -> elevated control. */
QMainWindow, QWidget#root, QScrollArea, QWidget#scrollContent {{
    background: {theme.page};
    border: none;
}}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QWidget#sidebar {{
    background: {theme.sidebar};
    border-right: 1px solid {theme.border};
}}
QWidget#topBar {{
    background: {theme.card};
    border-bottom: 1px solid {theme.border};
}}
QWidget#topTabs {{
    background: {theme.page};
    border-bottom: 1px solid {theme.border};
}}
QLabel#appTitle, QLabel#pageTitle, QLabel#sectionTitle {{
    color: {theme.text};
}}
QLabel#appTitle {{ font-size: 18px; font-weight: 700; }}
QLabel#pageTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#sectionTitle {{ font-size: 15px; font-weight: 650; }}
QLabel#subText, QLabel#artistText, QLabel#timeText, QLabel#statusText,
QLabel#settingsCardDesc, QLabel#settingsKey {{ color: {theme.muted}; }}

/* EchoMusic cards: restrained borders, no hard square corners. */
QFrame#card, QFrame#settingsCard, QFrame#rankSongCard,
QFrame#kugouPanel, QFrame#memberCard {{
    background: {theme.card};
    border: 1px solid {theme.border};
    border-radius: 16px;
}}
QFrame#card:hover, QFrame#settingsCard:hover, QFrame#rankSongCard:hover,
QFrame#kugouPanel:hover {{
    border-color: {theme.border_strong};
}}
QFrame#card:hover {{
    background: {theme.hover};
}}
QFrame#settingsCard:hover, QFrame#rankSongCard:hover, QFrame#kugouPanel:hover {{
    background: {theme.card};
}}
QFrame#card[selected="true"] {{
    background: {theme.selected};
    border: 1px solid {theme.accent};
}}
QFrame#categoryCard, QFrame#categoryCard[selected="true"] {{
    background: transparent;
    border: none;
}}
QLabel#settingsCardTitle, QLabel#rankCardTitle, QLabel#guideTitle {{
    color: {theme.text};
    font-weight: 700;
}}
QLabel#settingsCardTitle {{ font-size: 15px; }}
QLabel#rankCardTitle {{ font-size: 17px; }}
QLabel#rankSongName, QLabel#rankSongIndex {{ color: {theme.text}; }}
QLabel#rankSongArtist, QLabel#rankCardFreq, QLabel#rankDate,
QLabel#rankStats {{ color: {theme.muted}; }}

/* Inputs and action controls follow EchoMusic's soft control surface. */
QLineEdit#searchEdit, QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    color: {theme.text};
    background: {theme.card};
    border: 1px solid {theme.border};
    border-radius: 10px;
    padding: 6px 10px;
    selection-background-color: {theme.accent};
    selection-color: {theme.text};
}}
QLineEdit#searchEdit:focus, QLineEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {theme.accent};
}}
QComboBox {{
    color: {theme.text};
    background: {theme.elevated};
    border: none;
    border-radius: 10px;
    padding: 6px 10px;
    outline: none;
}}
QComboBox:hover {{
    color: {theme.text};
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(255, 255, 255, 0.16),
        stop: 0.45 rgba(255, 255, 255, 0.06),
        stop: 0.52 rgba(255, 255, 255, 0.24),
        stop: 1 rgba(255, 255, 255, 0.12));
    border: none;
}}
QComboBox:focus {{ border: none; outline: none; }}
QComboBox::drop-down {{ border: none; background: transparent; }}
QComboBox QAbstractItemView, QComboBoxPrivateContainer {{
    color: {theme.text};
    background: {theme.popup};
    border: none;
    border-radius: 12px;
    outline: none;
    padding: 4px;
}}
QFrame#settingsCard QComboBox QAbstractItemView {{
    background: {theme.card};
    border: none;
    border-radius: 14px;
}}
QComboBox QAbstractItemView::item {{
    color: {theme.text};
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 7px 10px;
}}
QComboBox QAbstractItemView::item:hover {{
    color: {theme.text};
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(255, 255, 255, 0.16),
        stop: 0.45 rgba(255, 255, 255, 0.06),
        stop: 0.52 rgba(255, 255, 255, 0.24),
        stop: 1 rgba(255, 255, 255, 0.12));
    border: none;
}}
QComboBox QAbstractItemView::item:selected {{
    color: #ffffff;
    background: {theme.accent};
    border: none;
}}
QPushButton#swapButton, QPushButton#folderButton {{
    color: #ffffff;
    background: {theme.accent};
    border: none;
    border-radius: 10px;
    padding: 7px 16px;
    font-weight: 650;
}}
QPushButton#swapButton:hover, QPushButton#folderButton:hover {{
    background: {theme.accent_hover};
}}
QPushButton#normalButton, QPushButton#kugouButton, QPushButton#userChip {{
    color: {theme.text};
    background: {theme.elevated};
    border: 1px solid {theme.border};
    border-radius: 10px;
    padding: 6px 13px;
}}
QPushButton#normalButton:hover, QPushButton#kugouButton:hover,
QPushButton#userChip:hover {{
    background: {theme.hover};
    border-color: {theme.border_strong};
}}
QPushButton#textButton {{
    color: {theme.accent};
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px 8px;
}}
QPushButton#textButton:hover {{ background: {theme.accent_soft}; }}
QPushButton#topTab {{
    color: {theme.muted};
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 4px 6px;
}}
QPushButton#topTab:hover {{ color: {theme.text}; }}
QPushButton#topTab:checked {{
    color: {theme.accent};
    border-bottom-color: {theme.accent};
    font-weight: 650;
}}

/* Sidebar navigation and page lists use EchoMusic's quiet row states. */
QListWidget#sidebarList {{
    background: transparent;
    border: none;
    color: {theme.text};
}}
QListWidget#sidebarList::item {{
    color: {theme.muted};
    height: 42px;
    margin: 2px 10px;
    padding-left: 14px;
    border: 1px solid transparent;
    border-radius: 10px;
}}
QListWidget#sidebarList::item:hover {{
    color: {theme.text};
    background: {theme.hover};
}}
QListWidget#sidebarList::item:selected {{
    color: {theme.accent};
    background: {theme.selected};
    border-color: transparent;
    font-weight: 650;
}}
QTableWidget#songTable, QListWidget#queueList, QListWidget#lyricList,
QListWidget#commentList {{
    background: transparent;
    border: none;
    outline: none;
}}
QTableWidget#songTable::item {{
    color: {theme.text};
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 6px 8px;
}}
QTableWidget#songTable::item:hover {{
    background: transparent;
    border: none;
}}
/* Selection is painted by the title-only delegate; never draw a border per cell. */
QTableWidget#songTable::item:selected {{
    color: {theme.text};
    background: transparent;
    border: none;
}}
QHeaderView::section {{
    color: {theme.muted};
    background: transparent;
    border: none;
    padding: 7px 8px;
    font-weight: 600;
}}

/* Scrollbars, menus and dialogs use the same local surface as their owner. */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    border: none;
    margin: 2px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {theme.border_strong};
    border-radius: 5px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {theme.accent};
}}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; border: none; }}
QMenu, QToolTip, QDialog, QMessageBox {{
    color: {theme.text};
    background: {theme.popup};
    border: 1px solid {theme.border};
    border-radius: 12px;
}}
QMenu {{ padding: 5px; }}
QMenu::item {{
    color: {theme.text};
    background: transparent;
    border-radius: 8px;
    padding: 7px 14px;
    margin: 1px 2px;
}}
QMenu::item:selected {{ color: {theme.text}; background: {theme.selected}; }}
QToolTip {{ padding: 6px 9px; }}
QCheckBox {{ color: {theme.text}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    background: {theme.card}; border: 1px solid {theme.border_strong};
}}
QCheckBox::indicator:hover {{ border-color: {theme.accent}; }}
QCheckBox::indicator:checked {{ background: {theme.accent}; border-color: {theme.accent}; }}

/*
 * Player backgrounds are intentionally not part of the palette system.
 * They are the original Meemaw surfaces and must stay stable while the
 * regular pages use the EchoMusic palette.  Only the quality/speed controls
 * below are allowed to add a soft local surface on top of this background.
 */
    QWidget#playerBar {{
        background: transparent;
        border-top: none;
    }}
    QWidget#nowPlayingPage {{
        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 #4a4a4a, stop: 1 #343434);
    }}
    QFrame#nowPlayingCard {{
        background: transparent;
        border: none;
        border-radius: 18px;
    }}
    QLabel#nowPlayingTitle {{ color: {theme.text}; font-size: 26px; font-weight: 800; }}
    QLabel#nowPlayingMeta {{ color: {theme.muted}; font-size: 13px; }}
    QLabel#metaKey {{ color: {theme.muted}; font-size: 12px; }}
    QLabel#metaValue {{ color: {theme.text}; font-size: 13px; }}
    QFrame#queuePanel, QFrame#lyricsPanel, QFrame#commentsPanel {{
        background: {theme.panel};
        border: 1px solid {theme.border};
        border-radius: 18px;
    }}
    QWidget#playerBar QPushButton, QWidget#nowPlayingPage QPushButton {{ border-radius: 10px; }}
    QWidget#playerBar QPushButton:hover, QWidget#nowPlayingPage QPushButton:hover {{ border-radius: 10px; }}
    QWidget#nowPlayingPage QComboBox#qualityCombo {{
        color: #e8e8ec;
        background: transparent;
        border: none;
        border-radius: 14px;
        padding: 5px 8px 5px 12px;
    }}
    QWidget#nowPlayingPage QComboBox#qualityCombo:hover {{
        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 rgba(255, 255, 255, 0.16),
            stop: 0.45 rgba(255, 255, 255, 0.06),
            stop: 0.52 rgba(255, 255, 255, 0.24),
            stop: 1 rgba(255, 255, 255, 0.12));
        border: none;
    }}
    QWidget#nowPlayingPage QComboBox#qualityCombo QAbstractItemView {{
        color: #e8e8ec;
        background: #343434;
        border: none;
        border-radius: 14px;
        selection-background-color: #ec4141;
        selection-color: #ffffff;
    }}
    QWidget#playerBar QComboBox#qualityCombo QAbstractItemView {{
        color: #e8e8ec;
        background: #211e1c;
        border: none;
        border-radius: 14px;
        selection-background-color: #ec4141;
        selection-color: #ffffff;
    }}
    QWidget#nowPlayingPage QComboBox#qualityCombo QAbstractItemView::item,
    QWidget#playerBar QComboBox#qualityCombo QAbstractItemView::item {{
        background: transparent;
        border: none;
        border-radius: 8px;
    }}
    QWidget#nowPlayingPage QComboBox#qualityCombo QAbstractItemView::item:hover,
    QWidget#playerBar QComboBox#qualityCombo QAbstractItemView::item:hover {{
        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 rgba(255, 255, 255, 0.16),
            stop: 0.45 rgba(255, 255, 255, 0.06),
            stop: 0.52 rgba(255, 255, 255, 0.24),
            stop: 1 rgba(255, 255, 255, 0.12));
        border: none;
    }}
    QWidget#playerBar QComboBox#qualityCombo {{
        color: #e8e8ec;
        background: transparent;
        border: none;
        border-radius: 14px;
    }}
    QWidget#playerBar QLabel#songTitle {{ color: {theme.text}; }}
    QWidget#playerBar QLabel#artistText, QWidget#playerBar QLabel#timeText {{ color: {theme.muted}; }}
    QWidget#playerBar QSlider::groove:horizontal,
    QWidget#nowPlayingPage QSlider::groove:horizontal {{
        height: 4px; background: {theme.border}; border-radius: 2px;
    }}
    QWidget#playerBar QSlider::sub-page:horizontal,
    QWidget#nowPlayingPage QSlider::sub-page:horizontal {{
        background: {theme.accent}; border-radius: 2px;
    }}
    QWidget#playerBar QSlider::handle:horizontal,
    QWidget#nowPlayingPage QSlider::handle:horizontal {{
        width: 12px; height: 12px; margin: -4px 0;
        background: {theme.text}; border: none; border-radius: 8px;
    }}
    QWidget#playerBar QSlider::handle:horizontal:hover,
    QWidget#playerBar QSlider::handle:horizontal:pressed,
    QWidget#nowPlayingPage QSlider::handle:horizontal:hover,
    QWidget#nowPlayingPage QSlider::handle:horizontal:pressed {{
        width: 16px; height: 16px; margin: -6px 0;
        background: {theme.text}; border: none; border-radius: 8px;
    }}
    QWidget#playerBar QSlider::groove:horizontal:hover,
    QWidget#nowPlayingPage QSlider::groove:horizontal:hover {{ height: 6px; border-radius: 3px; }}
    QWidget#playerBar QSlider::sub-page:horizontal:hover,
    QWidget#nowPlayingPage QSlider::sub-page:horizontal:hover {{ border-radius: 3px; }}
    QWidget#nowPlayingPage QLabel#lyricSectionTitle {{
        color: {theme.text}; border-bottom-color: {theme.accent};
    }}
    QListWidget#queueList, QListWidget#lyricList, QListWidget#commentList {{
        background: transparent; border: none; border-radius: 14px; outline: none;
    }}
    QListWidget#queueList::item {{
        height: 40px; padding: 0 10px; margin: 2px 4px;
        border: 1px solid transparent; border-radius: 10px;
        color: {theme.text}; background: transparent;
    }}
    QListWidget#queueList::item:hover {{
        background: {theme.hover}; border-color: {theme.border};
    }}
    QListWidget#queueList::item:selected {{
        background: {theme.selected}; color: {theme.accent};
        border-color: {theme.border_strong};
    }}
    QListWidget#lyricList::item {{
        padding: 2px 0; margin: 0; border: none; border-radius: 8px;
    }}
    QListWidget#commentList::item {{
        color: {theme.text}; background: transparent;
        border-bottom: 1px solid {theme.border};
        border-radius: 8px; margin: 1px 2px; padding: 8px 4px;
    }}
    QFrame#volumePopup {{
        background: {theme.popup}; border: 1px solid {theme.border}; border-radius: 12px;
    }}
    QLabel#volumePercent {{ color: {theme.text}; font-size: 13px; font-weight: 700; }}
    QWidget#trayPlayerPopup, QFrame#trayPlayerCard {{ background: transparent; }}
    QLabel#traySongTitle {{ color: {theme.text}; }}
    QLabel#traySongArtist, QLabel#trayTime {{ color: {theme.muted}; }}
    QSlider#trayProgress::groove:horizontal {{ height: 3px; background: {theme.border}; border-radius: 2px; }}
    QSlider#trayProgress::sub-page:horizontal {{ background: {theme.accent}; border-radius: 2px; }}
    QSlider#trayProgress::handle:horizontal {{
        width: 8px; height: 8px; margin: -2px 0; background: {theme.text};
        border: none; border-radius: 4px;
    }}
    QLabel#trayMenuText {{ color: {theme.text}; }}
    QLabel#trayMenuCheck {{ color: {theme.accent}; }}
    QLabel#trayMenuArrow {{ color: {theme.muted}; }}

"""


__all__ = ["Theme", "ThemeManager", "get_theme_manager", "current_theme", "available_themes", "set_theme", "apply_theme_palette", "THEMES"]
