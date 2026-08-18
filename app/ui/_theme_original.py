APP_QSS = """
* {
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC";
    font-size: 13px;
    color: #d7d7dc;
    outline: none;
}
QMainWindow, QWidget#root {
    background: #211e1c;
}
QScrollArea {
    background: #211e1c;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QWidget#scrollContent {
    background: #211e1c;
}
QWidget#sidebar {
    background: #191613;
    border-right: 1px solid #2d2823;
}
QWidget#topBar {
    background: #2b2622;
    border-bottom: 1px solid #39322c;
}
QWidget#topTabs {
    background: #211e1c;
    border-bottom: 1px solid #39322c;
}
QWidget#playerBar {
    background: transparent;
}
QToolTip {
    background: #322b27;
    color: #f2f2f5;
    border: 1px solid #5a4c42;
    border-radius: 12px;
    padding: 6px 10px;
    font-size: 12px;
}
QMenu {
    background: #2f2925;
    border: 1px solid #4a3f37;
    border-radius: 16px;
    padding: 6px;
}
QMenu::item {
    border-radius: 10px;
    padding: 8px 18px;
    margin: 2px 4px;
    color: #e8e8ec;
}
QMenu::item:selected {
    background: #ec4141;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 0.10);
    margin: 6px 10px;
    border: none;
}
QLabel#appTitle {
    color: #ffffff;
    font-size: 18px;
    font-weight: 800;
}
QLabel#pageTitle {
    color: #ffffff;
    font-size: 22px;
    font-weight: 800;
}
QLabel#sectionTitle {
    color: #ffffff;
    font-size: 16px;
    font-weight: 700;
}
QPushButton#swapButton {
    color: #ffffff;
    background: #ec4141;
    border: none;
    border-radius: 15px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#swapButton:hover {
    background: #ff5b52;
}
QPushButton#swapButton:disabled {
    background: #6f3a38;
    color: rgba(255, 255, 255, 0.55);
}
QLabel#subText, QLabel#artistText, QLabel#timeText, QLabel#statusText {
    color: #8f9299;
    font-size: 12px;
}
QLabel#songTitle {
    color: #ffffff;
    font-size: 14px;
    font-weight: 600;
}
QLabel#rankTitle {
    color: #ffffff;
    font-size: 26px;
    font-weight: 800;
}
QLabel#rankDesc {
    color: rgba(255, 255, 255, 0.82);
    font-size: 12px;
}
QLabel#rankDate {
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
}
QLabel#rankStats {
    color: rgba(255, 255, 255, 0.78);
    font-size: 12px;
}
QLabel#nowPlayingTitle {
    color: #ffffff;
    font-size: 26px;
    font-weight: 800;
}
QLabel#nowPlayingMeta {
    color: #9a9da4;
    font-size: 13px;
}
QLabel#metaKey {
    color: #8f9299;
    font-size: 12px;
    min-width: 0px;
}
QLabel#metaValue {
    color: #c9ccd1;
    font-size: 13px;
}
QLabel#lyricSectionTitle {
    color: #ffffff;
    font-size: 16px;
    font-weight: 700;
    border-bottom: 2px solid #ec4141;
    padding-bottom: 2px;
}
QFrame#rankSongCard {
    background: #212127;
    border: none;
    border-radius: 30px;
}
QFrame#rankSongCard:hover {
    background: #26262e;
}
QFrame#settingsCard {
    background: #2b2622;
    border: 1px solid #3a332d;
    border-radius: 26px;
}
QFrame#settingsCard:hover {
    border-color: #57493f;
    background: #2f2925;
}
QLabel#settingsCardTitle {
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
}
QLabel#settingsCardDesc, QLabel#settingsKey {
    color: #8f9299;
    font-size: 12px;
}
QLabel#settingsValue {
    color: #d7d7dc;
    font-size: 13px;
}
QLabel#rankCardTitle {
    color: #ffffff;
    font-size: 18px;
    font-weight: 800;
}
QLabel#rankCardFreq {
    color: rgba(255, 255, 255, 0.84);
    font-size: 12px;
}
QLabel#rankSongIndex {
    color: rgba(255, 255, 255, 0.9);
    font-size: 13px;
    font-weight: 700;
    min-width: 20px;
}
QLabel#rankSongName {
    color: #ffffff;
    font-size: 13px;
}
QLabel#rankSongArtist {
    color: rgba(255, 255, 255, 0.72);
    font-size: 12px;
}
QFrame#nowPlayingCard {
    background: transparent;
    border: none;
    border-radius: 0;
}
QWidget#nowPlayingPage {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #4a4a4a,
        stop: 1 #343434
    );
}
QListWidget#sidebarList {
    background: transparent;
    border: none;
    font-size: 14px;
}
QListWidget#sidebarList::item {
    height: 46px;
    padding-left: 14px;
    margin: 4px 12px;
    color: #b5b8bf;
    border: none;
    border-radius: 14px;
}
QListWidget#sidebarList::item:hover {
    background: #2b2521;
    color: #ffffff;
}
QListWidget#sidebarList::item:selected {
    background: #d84a3f;
    color: #ffffff;
    font-weight: 700;
}
QListWidget#queueList {
    background: transparent;
    border: none;
}
QListWidget#queueList::item {
    height: 40px;
    padding: 0 10px;
    color: #cfcfd6;
}
QListWidget#queueList::item:hover {
    background: #2a2a31;
}
QListWidget#queueList::item:selected {
    background: #3a2223;
    color: #ec4141;
}
QListWidget#lyricList {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget#lyricList::item {
    padding: 2px 0;
    border: none;
}
QLineEdit#searchEdit {
    background: #3a322c;
    border: 1px solid transparent;
    border-radius: 23px;
    padding: 9px 20px;
    color: #f2f2f5;
    selection-background-color: #ec4141;
}
QLineEdit#searchEdit:focus {
    border: 1px solid #ec4141;
}
QComboBox {
    background: #38302b;
    border: 1px solid #4a3f37;
    border-radius: 12px;
    padding: 6px 12px;
    min-width: 110px;
    color: #e8e8ec;
}
QComboBox:hover {
    border: 1px solid #6a594d;
}
QComboBox#qualityCombo, QComboBox#deviceCombo {
    background: rgba(46, 39, 35, 0.94);
    border: 1px solid #4a3f37;
    border-radius: 12px;
    padding: 5px 8px 5px 12px;
    min-width: 96px;
    color: #e8e8ec;
    font-size: 12px;
}
QComboBox#qualityCombo:hover, QComboBox#deviceCombo:hover {
    border: 1px solid #6a594d;
}
QComboBox#qualityCombo::drop-down, QComboBox#deviceCombo::drop-down {
    border: none;
    width: 0;
    subcontrol-position: center right;
}
QComboBox#qualityCombo::down-arrow, QComboBox#deviceCombo::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
QComboBox QAbstractItemView {
    background: #2f2925;
    border: 1px solid #4a3f37;
    border-radius: 12px;
    color: #e8e8ec;
    selection-background-color: #ec4141;
    selection-color: #ffffff;
}
QTableWidget {
    background: transparent;
    border: none;
    gridline-color: transparent;
    alternate-background-color: #26211d;
}
QTableWidget#songTable::item {
    background: transparent;
    border: none;
    padding: 0 6px;
    color: #d7d7dc;
}
QTableWidget#songTable::item:hover {
    background: transparent;
}
QTableWidget#songTable::item:selected {
    background: transparent;
    color: #ffffff;
}
QTableWidget::item {
    border-bottom: 1px solid #312a25;
    padding: 0 6px;
    color: #d7d7dc;
}
QTableWidget::item:hover {
    background: #332b26;
}
QTableWidget::item:selected {
    background: #462e28;
    color: #ffffff;
}
QHeaderView::section {
    background: #26211d;
    color: #8f9299;
    border: none;
    border-bottom: 1px solid #39322c;
    padding: 8px 6px;
    font-size: 12px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #5a4c42;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #756254;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: #5a4c42;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #3d3631;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #e24a3d;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    margin: -4px 0;
    background: #ffffff;
    border: none;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    background: #ffffff;
}
QSlider::handle:horizontal:pressed {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    background: #ffffff;
}
QSlider::groove:horizontal:hover {
    height: 6px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal:hover {
    border-radius: 3px;
}
QFrame#volumePopup {
    background: rgba(34, 30, 28, 248);
    border: 1px solid rgba(70, 61, 54, 0.35);
    border-radius: 12px;
}
QLabel#volumePercent {
    color: #ffffff;
    font-size: 13px;
    font-weight: 700;
}
QLabel#commentMoreText {
    color: #7d8087;
    font-size: 11px;
    padding: 4px 0 2px 0;
}
QPushButton#userChip {
    color: #e8e8ec;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid #4a3f37;
    border-radius: 14px;
    padding: 6px 14px;
    font-size: 12px;
}
QPushButton#userChip:hover {
    color: #ffffff;
    border-color: #6a594d;
    background: rgba(255, 255, 255, 0.14);
}
QFrame#kugouPanel {
    background: #2b2622;
    border: 1px solid #3a332d;
    border-radius: 22px;
}
QFrame#memberCard {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
}
QLabel#memberCardTitle {
    color: #ffffff;
    font-size: 13px;
    font-weight: 700;
}
QLabel#memberRow {
    color: #d6d2cd;
    font-size: 12px;
}
QLabel#guideTitle {
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
}
QPushButton#kugouButton {
    background: #38302b;
    border: 1px solid #4a3f37;
    border-radius: 12px;
    color: #e8e8ec;
    padding: 7px 12px;
}
QPushButton#kugouButton:hover {
    background: #403631;
    border-color: #6a594d;
}
QPushButton#textButton {
    background: transparent;
    border: none;
    color: #ec4141;
    padding: 4px 10px;
}
QPushButton#textButton:hover {
    color: #ff6b6b;
}
QPushButton#normalButton {
    background: #38302b;
    border: 1px solid #4a3f37;
    border-radius: 12px;
    color: #e8e8ec;
    padding: 6px 14px;
}
QPushButton#normalButton:hover {
    background: #403631;
    border-color: #6a594d;
}
QPushButton#folderButton {
    background: #ec4141;
    border: none;
    border-radius: 12px;
    color: #ffffff;
    font-weight: 600;
    padding: 7px 16px;
}
QPushButton#folderButton:hover {
    background: #ff5252;
}
QFrame#card {
    background: #2b2622;
    border: 1px solid transparent;
    border-radius: 20px;
}
QFrame#card:hover {
    background: #332b26;
    border-color: #57493f;
}
QFrame#card[selected="true"] {
    border: 2px solid #ec4141;
    background: #382f2a;
}
QFrame#categoryCard {
    border: none;
}
QFrame#categoryCard[selected="true"] {
    border: none;
}
QFrame#queuePanel {
    background: #26211d;
    border-left: 1px solid #39322c;
}
QFrame#lyricsPanel {
    background: #26211d;
    border-left: 1px solid #39322c;
}
QWidget#trayPlayerPopup {
    background: transparent;
}
QFrame#trayPlayerCard {
      background: transparent;
      border: none;
      border-radius: 18px;
  }
QLabel#traySongTitle {
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
}
QLabel#traySongArtist {
    color: #9a9da4;
    font-size: 12px;
}
QLabel#trayTime {
    color: #9a9da4;
    font-size: 11px;
}
QSlider#trayProgress::groove:horizontal {
    height: 3px;
    background: #3d3631;
    border-radius: 2px;
}
QSlider#trayProgress::sub-page:horizontal {
    background: #ec4141;
    border-radius: 2px;
}
QSlider#trayProgress::handle:horizontal {
    width: 8px;
    height: 8px;
    margin: -2px 0;
    background: #ffffff;
    border: none;
    border-radius: 4px;
}
QFrame#trayDivider {
    background: #3a332d;
    border: none;
}
QWidget#trayMenuRow {
    border-radius: 10px;
}
QLabel#trayMenuText {
    color: #d7d7dc;
    font-size: 13px;
}
QLabel#trayMenuCheck {
    color: #ec4141;
    font-size: 13px;
    font-weight: 800;
}
QLabel#trayMenuArrow {
    color: #7d8087;
    font-size: 18px;
}
QLabel#trayBrand {
    color: rgba(255, 255, 255, 0.55);
    font-size: 11px;
    font-weight: 700;
}
QFrame#commentsPanel {
    background: #26211d;
    border-left: 1px solid #39322c;
}
QListWidget#commentList {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget#commentList::item {
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    padding: 8px 4px;
}
QPushButton#topTab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #8f9299;
    font-size: 14px;
    padding: 8px 2px 6px 2px;
}
QPushButton#topTab:hover {
    color: #e8e8ec;
}
QPushButton#topTab:checked {
    color: #ec4141;
    font-weight: 700;
    border-bottom: 2px solid #ec4141;
}
QLabel#emptyLabel {
    color: #7d8087;
    font-size: 14px;
}
"""
