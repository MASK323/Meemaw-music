"""Theme compatibility layer for the original Meemaw UI.

The original widgets, page layout and animations remain in charge of the UI.
This module only adds the same soft surface treatment to the controls that the
original stylesheet did not cover, while resolving every colour from the
currently loaded theme.  There is intentionally no appearance/settings page
here: the theme is an internal palette used by the existing UI.
"""
from app.ui._theme_original import APP_QSS as _ORIGINAL_APP_QSS
from app.core.theme_manager import get_theme_manager, apply_theme_palette


def _rounded_surfaces(theme) -> str:
    """Return rounded rules using the owning surface's palette tokens."""
    template = '\n/* Local page surfaces: keep each panel on the same palette layer as its owner. */\nQFrame#queuePanel, QFrame#lyricsPanel, QFrame#commentsPanel {\n    background: {panel};\n    border: 1px solid {border};\n    border-radius: 18px;\n}\nQFrame#queuePanel:hover, QFrame#lyricsPanel:hover, QFrame#commentsPanel:hover {\n    border-color: {border_strong};\n}\nQListWidget#queueList, QListWidget#lyricList, QListWidget#commentList,\nQTableWidget#songTable {\n    background: transparent;\n    border: none;\n    border-radius: 14px;\n    outline: none;\n}\nQListWidget#queueList::item, QListWidget#lyricList::item,\nQListWidget#commentList::item {\n    background: transparent;\n    border: 1px solid transparent;\n    border-radius: 10px;\n    margin: 2px 4px;\n    padding: 7px 8px;\n}\nQListWidget#queueList::item:hover, QListWidget#lyricList::item:hover,\nQListWidget#commentList::item:hover {\n    background: {hover};\n    border-color: {border};\n}\nQListWidget#queueList::item:selected, QListWidget#lyricList::item:selected,\nQListWidget#commentList::item:selected {\n    background: {selected};\n    border-color: {border_strong};\n}\nQTableWidget#songTable::item, QTableWidget::item {\n    background: transparent;\n    border: none;\n    border-radius: 10px;\n    padding: 6px 8px;\n}\nQTableWidget#songTable::item:hover, QTableWidget::item:hover {\n    background: transparent;\n    border: none;\n}\n/* Selection is painted by the title-only delegate; never draw a border per cell. */\nQTableWidget#songTable::item:selected, QTableWidget::item:selected {\n    background: transparent;\n    border: none;\n}\nQHeaderView::section {\n    background: {elevated};\n    color: {muted};\n    border: none;\n    border-radius: 8px;\n    padding: 7px 8px;\n}\n\n/* Soft controls: no square edges are left when a page changes. */\nQLineEdit, QComboBox, QPushButton, QToolButton { border-radius: 10px; }\nQFrame, QGroupBox, QProgressBar, QTabWidget::pane, QAbstractScrollArea {\n    border-radius: 12px;\n}\nQSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {\n    border-radius: 10px;\n}\nQAbstractItemView, QListView, QTreeView, QTableView {\n    border-radius: 12px;\n    outline: none;\n}\nQToolButton, QPushButton, QComboBox, QLineEdit, QPlainTextEdit,\nQSpinBox, QDoubleSpinBox, QProgressBar, QTabBar::tab {\n    border-radius: 10px;\n}\nQScrollBar:vertical, QScrollBar:horizontal {\n    background: transparent;\n    border: none;\n    border-radius: 7px;\n}\nQScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,\nQScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,\nQScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,\nQScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {\n    background: transparent;\n    border: none;\n    border-radius: 7px;\n}\nQToolTip, QMenu, QComboBox QAbstractItemView, QComboBoxPrivateContainer {\n    border-radius: 12px;\n}\nQComboBox#qualityCombo, QComboBox#deviceCombo,\nQComboBox#playbackSpeed, QComboBox#nowPlayingPlaybackSpeed {\n    border-radius: 14px;\n}\nQMenu::item:selected, QMenu::item:hover,\nQPushButton:hover, QPushButton:disabled, QPushButton:checked,\nQToolButton:hover, QLineEdit:focus, QComboBox:hover,\nQComboBox#qualityCombo:hover, QComboBox#deviceCombo:hover,\nQFrame#rankSongCard:hover, QFrame#settingsCard:hover,\nQFrame#card:hover, QFrame#card[selected="true"],\nQListWidget#sidebarList::item:hover, QListWidget#sidebarList::item:selected,\nQSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed,\nQScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {\n    border-radius: 10px;\n}\n'
    for attr in ['panel', 'border', 'border_strong', 'hover', 'border', 'selected', 'border_strong', 'hover', 'border', 'selected', 'accent', 'elevated', 'muted']:
        template = template.replace("{" + attr + "}", str(getattr(theme, attr)))
    return template


def _build_stylesheet():
    manager = get_theme_manager()
    theme = manager.current()
    return apply_theme_palette(_ORIGINAL_APP_QSS + "\n" + _rounded_surfaces(theme), theme)


APP_QSS = _build_stylesheet()
__all__ = ["APP_QSS"]
