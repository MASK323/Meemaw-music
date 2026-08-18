"""Settings-only extension for the original Meemaw pages.

The original pages, widgets, theme, colors and transitions are kept intact.
This module only adds the requested custom audio-source and external-playlist
controls to the existing SettingsPage.
"""
from __future__ import annotations

import json
import re

from app.ui._pages_original import *  # noqa: F401,F403
from app.ui._pages_original import SettingsPage as _OriginalSettingsPage
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SettingsPage(_OriginalSettingsPage):
    """Original settings page with only the requested source/playlist cards."""

    def __init__(self, window):
        super().__init__(window)
        self._source_manager = None
        self._source_list = None
        self._source_fields = {}
        self._source_form_widget = None
        self._source_action_buttons = {}
        self._source_enabled = None
        self._source_lock_hint = None
        self._source_status = None
        self._playlist_provider = None
        self._playlist_input = None
        self._playlist_status = None
        self._playlist_progress = None
        self._source_card = None
        self._playlist_card = None
        self._install_extra_settings()
        QTimer.singleShot(0, self._install_extra_settings)

    def _settings_layout(self):
        content = self.findChild(QWidget, "scrollContent")
        if content is None:
            scroll = self.findChild(QScrollArea)
            content = scroll.widget() if scroll is not None else self
        return content.layout() if content is not None else None

    def _install_extra_settings(self) -> None:
        if getattr(self, "_extra_settings_installed", False):
            return
        layout = self._settings_layout()
        if layout is None:
            return
        self._extra_settings_installed = True
        from app.core.source_manager import get_source_manager
        self._source_manager = get_source_manager()
        self._source_card = self._build_source_card()
        self._playlist_card = self._build_playlist_card()
        # Keep the original settings cards and stylesheet untouched. Add the
        # requested cards immediately before the original trailing stretch.
        index = max(0, layout.count() - 1)
        layout.insertWidget(index, self._source_card)
        layout.insertWidget(index + 1, self._playlist_card)
        self._refresh_source_list()
        self._fit_combo_popups()
        # Qt can recreate the transient popup window after the page is shown;
        # repeat the sizing a couple of times so the first open is correct.
        QTimer.singleShot(0, self._fit_combo_popups)
        QTimer.singleShot(48, self._fit_combo_popups)

    def _fit_combo_popups(self) -> None:
        """Apply the rounded, surface-matching popup treatment to every combo."""
        from app.ui.widgets import _fit_option_combo_popup, fit_all_combo_popups
        for combo in (self._playlist_provider, getattr(self, "_quality", None), getattr(self, "_device", None)):
            if combo is not None:
                _fit_option_combo_popup(combo)
        # Cover every other combo in the window (charts selector, player-bar
        # quality, now-playing quality) so each dropdown matches its surface.
        try:
            window = self.window()
        except RuntimeError:
            window = None
        if window is not None and window is not self:
            fit_all_combo_popups(window)
        fit_all_combo_popups(self)

    @staticmethod
    def _label(text: str, object_name: str = "settingsHint") -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        return label

    def _field(self, form: QVBoxLayout, label_text: str, key: str, placeholder: str = "") -> QLineEdit:
        form.addWidget(self._label(label_text, "settingsKey"))
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        self._source_fields[key] = field
        form.addWidget(field)
        return field

    def _build_source_card(self) -> QFrame:
        card, layout = self._card(
            "音源管理",
            "默认使用酷狗概念版。可添加兼容 HTTP JSON 的自定义音源；优先级数字越小越优先，解析失败会自动切换后备音源。",
        )
        row = QHBoxLayout()
        self._source_list = QListWidget()
        self._source_list.setMinimumHeight(118)
        self._source_list.setMinimumWidth(220)
        self._source_list.currentItemChanged.connect(lambda current, _previous: self._load_source(current))
        row.addWidget(self._source_list, 1)

        form_widget = QWidget()
        form = QVBoxLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(5)
        self._field(form, "名称", "name", "例如：本地音源")
        self._field(form, "基础/搜索 API 地址", "base_url", "https://example.com/api/search")
        self._field(form, "搜索 URL 模板（可选）", "search_url", "支持 {keyword} {title} {artist} {quality}")
        self._field(form, "解析 URL 模板（可选）", "resolve_url", "支持 {id} {keyword} {quality}")
        self._field(form, "请求头 JSON（可选）", "headers", '{"Authorization":"Bearer ..."}')
        numbers = QHBoxLayout()
        priority = QSpinBox()
        priority.setRange(-100, 999)
        priority.setValue(50)
        timeout = QDoubleSpinBox()
        timeout.setRange(1.0, 15.0)
        timeout.setSingleStep(0.5)
        timeout.setValue(4.5)
        self._source_fields["priority"] = priority
        self._source_fields["timeout"] = timeout
        numbers.addWidget(self._label("优先级", "settingsKey"))
        numbers.addWidget(priority)
        numbers.addWidget(self._label("超时(秒)", "settingsKey"))
        numbers.addWidget(timeout)
        form.addLayout(numbers)
        row.addWidget(form_widget, 2)
        self._source_form_widget = form_widget
        layout.addLayout(row)

        self._source_lock_hint = self._label("内置音源 · 由 Meemaw 维护 · 不可编辑、删除或停用。")
        self._source_lock_hint.hide()
        layout.addWidget(self._source_lock_hint)

        buttons = QHBoxLayout()
        self._source_enabled = QCheckBox("启用当前音源")
        self._source_enabled.setChecked(True)
        buttons.addWidget(self._source_enabled)
        new = QPushButton("新建音源")
        new.setObjectName("normalButton")
        new.clicked.connect(self._new_source)
        save = QPushButton("添加/保存")
        save.setObjectName("normalButton")
        save.clicked.connect(self._save_source)
        delete = QPushButton("删除")
        delete.setObjectName("textButton")
        delete.clicked.connect(self._delete_source)
        toggle = QPushButton("切换启用")
        toggle.setObjectName("textButton")
        toggle.clicked.connect(self._toggle_source)
        test = QPushButton("测试音源")
        test.setObjectName("normalButton")
        test.clicked.connect(self._test_source)
        reset = QPushButton("恢复默认")
        reset.setObjectName("textButton")
        reset.clicked.connect(self._reset_sources)
        self._source_action_buttons = {"new": new, "save": save, "delete": delete, "toggle": toggle, "test": test, "reset": reset}
        for button in (new, save, delete, toggle, test, reset):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._source_status = self._label("选择音源后可编辑配置。")
        layout.addWidget(self._source_status)
        return card

    def _set_source_editor_enabled(self, enabled: bool) -> None:
        if self._source_form_widget is not None:
            self._source_form_widget.setEnabled(enabled)
        if self._source_enabled is not None:
            self._source_enabled.setEnabled(enabled)
        for key, button in self._source_action_buttons.items():
            if key in {"save", "delete", "toggle"}:
                button.setEnabled(enabled)
        if self._source_lock_hint is not None:
            self._source_lock_hint.setVisible(not enabled)

    def _refresh_source_list(self, select_id: str = "") -> None:
        if self._source_list is None or self._source_manager is None:
            return
        self._source_list.blockSignals(True)
        self._source_list.clear()
        selected = -1
        for index, source in enumerate(self._source_manager.sources()):
            state = "启用" if source.enabled else "停用"
            item = QListWidgetItem(f"{source.name}  ·  {state}  ·  P{source.priority}")
            item.setData(Qt.ItemDataRole.UserRole, source.id)
            self._source_list.addItem(item)
            if source.id == select_id:
                selected = index
        if self._source_list.count():
            self._source_list.setCurrentRow(selected if selected >= 0 else 0)
        self._source_list.blockSignals(False)
        self._load_source(self._source_list.currentItem())

    def _load_source(self, item) -> None:
        if item is None or self._source_manager is None:
            return
        source = self._source_manager.get(str(item.data(Qt.ItemDataRole.UserRole)))
        if source is None:
            return
        values = {
            "name": source.name,
            "base_url": source.base_url,
            "search_url": source.search_url,
            "resolve_url": source.resolve_url,
            "headers": json.dumps(source.headers, ensure_ascii=False),
        }
        for key, value in values.items():
            self._source_fields[key].setText(value)
        self._source_fields["priority"].setValue(source.priority)
        self._source_fields["timeout"].setValue(source.timeout)
        self._source_enabled.setChecked(source.enabled)
        locked = source.id == "kugou_concept"
        self._set_source_editor_enabled(not locked)
        self._source_status.setText(
            f"当前：{source.name} · 内置默认音源（只读）" if locked else f"当前：{source.name}（{source.kind}）"
        )

    def _selected_source_id(self) -> str:
        item = self._source_list.currentItem() if self._source_list else None
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def _new_source(self) -> None:
        self._set_source_editor_enabled(True)
        if self._source_list:
            self._source_list.clearSelection()
            self._source_list.setCurrentRow(-1)
        defaults = {"name": "", "base_url": "", "search_url": "", "resolve_url": "", "headers": "{}"}
        for key, value in defaults.items():
            self._source_fields[key].setText(value)
        self._source_fields["priority"].setValue(50)
        self._source_fields["timeout"].setValue(4.5)
        self._source_enabled.setChecked(True)
        self._source_status.setText("请输入配置后点击‘添加/保存’。")

    def _save_source(self) -> None:
        source_id = self._selected_source_id()
        name = self._source_fields["name"].text().strip() or "自定义音源"
        if source_id == "kugou_concept":
            self._source_status.setText("默认酷狗概念版不可覆盖，请新建自定义音源。")
            return
        if not source_id:
            base_id = "custom_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "custom_source"
            source_id = base_id
            suffix = 2
            while self._source_manager.get(source_id) is not None:
                source_id = f"{base_id}_{suffix}"
                suffix += 1
        try:
            headers = json.loads(self._source_fields["headers"].text() or "{}")
            if not isinstance(headers, dict):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            self._source_status.setText("请求头必须是 JSON 对象。")
            return
        self._source_manager.upsert({
            "id": source_id,
            "name": name,
            "kind": "http",
            "enabled": self._source_enabled.isChecked(),
            "priority": self._source_fields["priority"].value(),
            "base_url": self._source_fields["base_url"].text().strip(),
            "search_url": self._source_fields["search_url"].text().strip(),
            "resolve_url": self._source_fields["resolve_url"].text().strip(),
            "headers": headers,
            "timeout": self._source_fields["timeout"].value(),
        })
        self._refresh_source_list(source_id)
        self._source_status.setText("音源已保存，后续解析会自动使用新的优先级。")

    def _delete_source(self) -> None:
        source_id = self._selected_source_id()
        if not source_id:
            return
        if not self._source_manager.remove(source_id):
            self._source_status.setText("默认酷狗概念版不能删除。")
        else:
            self._refresh_source_list()
            self._source_status.setText("音源已删除。")

    def _toggle_source(self) -> None:
        source_id = self._selected_source_id()
        source = self._source_manager.get(source_id) if source_id else None
        if source is None or source_id == "kugou_concept":
            self._source_status.setText("默认酷狗概念版始终启用，不能切换。")
            return
        self._source_manager.set_enabled(source_id, not source.enabled)
        self._refresh_source_list(source_id)

    def _test_source(self) -> None:
        source_id = self._selected_source_id()
        if not source_id:
            return
        self._source_status.setText("正在测试音源…")
        self._window.run_task("source_test", lambda: self._source_manager.test_source(source_id), self._on_source_tested)

    def _on_source_tested(self, result) -> None:
        ok, message = result if isinstance(result, tuple) and len(result) >= 2 else (False, "测试失败")
        self._source_status.setText(("✓ " if ok else "✕ ") + str(message))

    def _reset_sources(self) -> None:
        self._source_manager.reset_defaults()
        self._refresh_source_list("kugou_concept")
        self._source_status.setText("已恢复默认酷狗概念版音源。")

    def _build_playlist_card(self) -> QFrame:
        card, layout = self._card(
            "导入外部歌单",
            "支持网易云音乐、QQ 音乐、Apple Music 的公开歌单，也支持每行一首‘歌名 - 歌手’的文本歌单。导入后会匹配到现有音源并加入播放队列。",
        )
        row = QHBoxLayout()
        self._playlist_provider = QComboBox()
        self._playlist_provider.setObjectName("playlistProviderCombo")
        self._playlist_provider.addItem("自动识别", "auto")
        self._playlist_provider.addItem("网易云音乐", "netease")
        self._playlist_provider.addItem("QQ 音乐", "qqmusic")
        self._playlist_provider.addItem("Apple Music", "apple")
        self._playlist_provider.addItem("文本歌单", "text")
        row.addWidget(self._playlist_provider)
        import_button = QPushButton("导入并匹配")
        import_button.setObjectName("normalButton")
        import_button.clicked.connect(self._import_playlist)
        row.addWidget(import_button)
        row.addStretch(1)
        layout.addLayout(row)
        self._playlist_input = QPlainTextEdit()
        self._playlist_input.setPlaceholderText("粘贴歌单链接 / ID，或输入多行：歌名 - 歌手")
        self._playlist_input.setFixedHeight(72)
        layout.addWidget(self._playlist_input)
        self._playlist_progress = QProgressBar()
        self._playlist_progress.setRange(0, 0)
        self._playlist_progress.hide()
        layout.addWidget(self._playlist_progress)
        self._playlist_status = self._label("尚未导入歌单。")
        layout.addWidget(self._playlist_status)
        return card

    def _import_playlist(self) -> None:
        value = self._playlist_input.toPlainText().strip() if self._playlist_input else ""
        if not value:
            self._playlist_status.setText("请先输入歌单链接、ID 或文本歌单。")
            return
        provider = self._playlist_provider.currentData() if self._playlist_provider else "auto"
        self._playlist_progress.show()
        self._playlist_status.setText("正在读取歌单并发匹配歌曲…")
        from app.core.playlist_importer import import_playlist
        self._window.run_task(
            "playlist_import",
            lambda: self._safe_import_playlist(import_playlist, value, provider),
            self._on_playlist_imported,
        )

    def _safe_import_playlist(self, importer, value: str, provider) -> dict:
        try:
            return importer(value, str(provider or "auto"), self._window.kugou)
        except Exception as exc:
            return {"error": str(exc), "songs": [], "matched": 0, "total": 0}

    def _on_playlist_imported(self, result) -> None:
        if self._playlist_progress:
            self._playlist_progress.hide()
        if not isinstance(result, dict):
            self._playlist_status.setText("歌单为空、需要登录，或读取失败。")
            return
        if result.get("error") and not result.get("songs"):
            self._playlist_status.setText(str(result.get("error")))
            return
        songs = result.get("songs") or []
        matched = int(result.get("matched") or len(songs))
        total = int(result.get("total") or 0)
        if not songs:
            self._playlist_status.setText("歌单为空、需要登录，或没有找到可匹配歌曲。")
            return
        try:
            self._window.player.play_queue(songs, 0)
        except Exception as exc:
            self._playlist_status.setText(f"已匹配 {matched} / {total} 首，但加入播放队列失败：{exc}")
            return
        self._playlist_status.setText(f"已匹配 {matched} / {total} 首，已加入播放队列。")


__all__ = [name for name in globals() if not name.startswith("_")]
