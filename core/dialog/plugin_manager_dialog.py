import os
from PySide6.QtCore import QFile, Qt, QSize
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QDialog,
    QListWidgetItem,
    QMessageBox,
    QLineEdit,
    QListWidget,
    QPushButton,
    QLabel,
    QTextBrowser,
    QDialogButtonBox
)
from PySide6.QtGui import QIcon, QPixmap
from core.i18n import tr
from core.dialog.create_plugin_dialog import CreatePluginDialog

class PluginManagerDialog(QDialog):
    def __init__(self, parent=None, plugin_manager=None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.plugins_metadata = []
        self.original_states = []  # 変更確認用の初期状態
        self.has_changes = False

        self._load_ui()
        self._setup_connections()
        self._load_plugins()

    def _load_ui(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ui_path = os.path.join(base_dir, "ui", "dialogs", "plugin_manager_dialog.ui")

        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise FileNotFoundError(f"Could not open UI file: {ui_path}")

        try:
            loader = QUiLoader()
            loaded = loader.load(ui_file, self)
        finally:
            ui_file.close()

        if loaded is None:
            raise RuntimeError(f"Could not load UI file: {ui_path}")

        self.setLayout(loaded.layout())

        # ウィジェットの取得
        self.lineSearch = self.findChild(QLineEdit, "lineSearch")
        self.listPlugins = self.findChild(QListWidget, "listPlugins")
        self.btnCreatePlugin = self.findChild(QPushButton, "btnCreatePlugin")
        self.labelName = self.findChild(QLabel, "labelName")
        self.labelId = self.findChild(QLabel, "labelId")
        self.labelVersion = self.findChild(QLabel, "labelVersion")
        self.labelPath = self.findChild(QLabel, "labelPath")
        self.labelTags = self.findChild(QLabel, "labelTags")
        self.labelDeps = self.findChild(QLabel, "labelDeps")
        self.textDescription = self.findChild(QTextBrowser, "textDescription")
        self.btnOpenFolder = self.findChild(QPushButton, "btnOpenFolder")
        self.buttonBox = self.findChild(QDialogButtonBox, "buttonBox")

        loaded.hide()

        # 詳細エリアの初期クリア
        self._clear_details()

    def _setup_connections(self):
        if self.lineSearch:
            self.lineSearch.textChanged.connect(self._filter_plugins)
        if self.listPlugins:
            self.listPlugins.currentItemChanged.connect(self._update_details)
            self.listPlugins.itemChanged.connect(self._on_item_changed)
        if self.btnOpenFolder:
            self.btnOpenFolder.clicked.connect(self._open_plugin_folder)
        if self.btnCreatePlugin:
            self.btnCreatePlugin.clicked.connect(self._create_new_plugin)
        if self.buttonBox:
            self.buttonBox.accepted.connect(self._on_accepted)
            self.buttonBox.rejected.connect(self.reject)

    def _load_plugins(self, select_id=None):
        if not self.plugin_manager:
            return

        # すべてのプラグイン情報を取得
        self.plugins_metadata = self.plugin_manager.get_all_plugins_metadata()
        
        # 変更検知用に初期状態をディープコピー（辞書のリスト）
        self.original_states = [{"id": p["id"], "enabled": p["enabled"]} for p in self.plugins_metadata]

        self._populate_list(select_id)

    def _populate_list(self, select_id=None):
        if not self.listPlugins:
            return

        # シグナルを一時ブロックして無限ループを防止
        self.listPlugins.blockSignals(True)
        self.listPlugins.clear()

        search_text = self.lineSearch.text().lower() if self.lineSearch else ""
        
        # 検索中（フィルタが空でない）ときは、意図しない並び替えを防ぐためドラッグを無効化
        self.listPlugins.setDragEnabled(search_text == "")

        selected_item = None

        for p in self.plugins_metadata:
            # 簡易フィルタリング（名前、ID、説明、タグにキーワードが含まれているか）
            name = p.get("name", "")
            p_id = p.get("id", "")
            desc = p.get("description", "")
            tags = p.get("tags", [])
            tags_str = ", ".join(tags)

            if search_text:
                match = (
                    search_text in name.lower() or
                    search_text in p_id.lower() or
                    search_text in desc.lower() or
                    search_text in tags_str.lower()
                )
                if not match:
                    continue

            # 表示テキストの構築（タグがあれば付与）
            display_text = name
            if tags:
                display_text += f" ({tags_str})"

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, p_id)
            
            # チェックボックスとドラッグ機能の有効化
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if p.get("enabled", True) else Qt.CheckState.Unchecked)

            # アイコンの設定
            if p.get("icon_path") and os.path.exists(p["icon_path"]):
                icon = QIcon(p["icon_path"])
                item.setIcon(icon)

            self.listPlugins.addItem(item)

            if select_id and p_id == select_id:
                selected_item = item

        self.listPlugins.blockSignals(False)

        # 新規作成時などの選択状態の復元
        if selected_item:
            self.listPlugins.setCurrentItem(selected_item)
        elif self.listPlugins.count() > 0:
            self.listPlugins.setCurrentRow(0)
        else:
            self._clear_details()

    def _filter_plugins(self, text):
        # 現在選択されているIDを保持
        current_item = self.listPlugins.currentItem()
        selected_id = current_item.data(Qt.UserRole) if current_item else None
        self._populate_list(selected_id)

    def _on_item_changed(self, item):
        p_id = item.data(Qt.UserRole)
        enabled = (item.checkState() == Qt.CheckState.Checked)
        
        # 現在のメモリ上の状態を取得
        p_info = next((p for p in self.plugins_metadata if p["id"] == p_id), None)
        if not p_info or p_info["enabled"] == enabled:
            return  # 変更がないか、再帰同期による呼び出し

        # シグナルブロックして連動中の無限ループを防止
        self.listPlugins.blockSignals(True)

        if enabled:
            # 有効化の検証
            deps = p_info.get("dependencies", [])
            missing_deps = []
            disabled_deps = []
            
            for dep in deps:
                dep_info = next((p for p in self.plugins_metadata if p["id"] == dep), None)
                if not dep_info:
                    missing_deps.append(dep)
                elif not dep_info["enabled"]:
                    disabled_deps.append(dep_info.get("name", dep))
                    
            if missing_deps:
                QMessageBox.warning(
                    self,
                    tr("有効化エラー", "PluginManager"),
                    tr("このプラグインは未インストールのプラグイン '{deps}' に依存しているため、有効にできません。").format(deps=", ".join(missing_deps))
                )
                item.setCheckState(Qt.CheckState.Unchecked)
            elif disabled_deps:
                reply = QMessageBox.question(
                    self,
                    tr("依存プラグインの有効化", "PluginManager"),
                    tr("プラグイン '{name}' を有効にするには、依存するプラグイン '{deps}' も有効にする必要があります。\n同時に有効にしますか？").format(
                        name=p_info.get("name", p_id),
                        deps=", ".join(disabled_deps)
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    # 再帰的に依存先を有効化
                    success, err = self._enable_plugin_recursive(p_id)
                    if not success:
                        QMessageBox.critical(self, tr("エラー", "PluginManager"), err)
                        item.setCheckState(Qt.CheckState.Unchecked)
                        p_info["enabled"] = False
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
            else:
                p_info["enabled"] = True
        else:
            # 無効化の検証
            dependent_plugins = []
            for p in self.plugins_metadata:
                if p["enabled"] and p_id in p.get("dependencies", []):
                    dependent_plugins.append(p.get("name", p["id"]))
                    
            if dependent_plugins:
                reply = QMessageBox.question(
                    self,
                    tr("依存関係の警告", "PluginManager"),
                    tr("プラグイン '{name}' を無効にすると、依存しているプラグイン '{deps}' も無効化されます。\n無効にしますか？").format(
                        name=p_info.get("name", p_id),
                        deps=", ".join(dependent_plugins)
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    # 再帰的に依存元を無効化
                    self._disable_plugin_recursive(p_id)
                else:
                    item.setCheckState(Qt.CheckState.Checked)
            else:
                p_info["enabled"] = False

        self.listPlugins.blockSignals(False)
        
        # 詳細表示と一覧表示の更新（赤字警告の状態が変わる可能性があるため）
        self._update_details(self.listPlugins.currentItem(), None)

    def _enable_plugin_recursive(self, p_id):
        p_info = next((p for p in self.plugins_metadata if p["id"] == p_id), None)
        if not p_info:
            return False, tr("プラグイン '{id}' が見つかりません（未インストール）。").format(id=p_id)
        
        if p_info["enabled"]:
            return True, ""
            
        for dep in p_info.get("dependencies", []):
            success, err = self._enable_plugin_recursive(dep)
            if not success:
                return False, err
                
        p_info["enabled"] = True
        self._update_list_item_check_state(p_id, Qt.CheckState.Checked)
        return True, ""

    def _disable_plugin_recursive(self, p_id):
        p_info = next((p for p in self.plugins_metadata if p["id"] == p_id), None)
        if not p_info or not p_info["enabled"]:
            return
            
        for p in self.plugins_metadata:
            if p["enabled"] and p_id in p.get("dependencies", []):
                self._disable_plugin_recursive(p["id"])
                
        p_info["enabled"] = False
        self._update_list_item_check_state(p_id, Qt.CheckState.Unchecked)

    def _update_list_item_check_state(self, p_id, state):
        for i in range(self.listPlugins.count()):
            item = self.listPlugins.item(i)
            if item.data(Qt.UserRole) == p_id:
                item.setCheckState(state)
                break

    def _clear_details(self):
        if self.labelName: self.labelName.setText(tr("プラグインが選択されていません", "PluginManager"))
        if self.labelId: self.labelId.setText("-")
        if self.labelVersion: self.labelVersion.setText("-")
        if self.labelPath: self.labelPath.setText("-")
        if self.labelTags: self.labelTags.setText("-")
        if self.labelDeps: self.labelDeps.setText("-")
        if self.textDescription: self.textDescription.clear()
        if self.btnOpenFolder: self.btnOpenFolder.setEnabled(False)
        self.current_selected_path = None

    def _update_details(self, current_item, previous_item):
        if not current_item:
            self._clear_details()
            return

        p_id = current_item.data(Qt.UserRole)
        plugin_info = None
        for p in self.plugins_metadata:
            if p["id"] == p_id:
                plugin_info = p
                break

        if not plugin_info:
            self._clear_details()
            return

        if self.labelName: self.labelName.setText(plugin_info.get("name", p_id))
        if self.labelId: self.labelId.setText(p_id)
        if self.labelVersion: self.labelVersion.setText(plugin_info.get("version", "1.0.0"))
        
        path = plugin_info.get("path", "")
        if self.labelPath:
            self.labelPath.setText(path)
            
        tags = plugin_info.get("tags", [])
        if self.labelTags:
            self.labelTags.setText(", ".join(tags) if tags else "-")
            
        deps = plugin_info.get("dependencies", [])
        if self.labelDeps:
            if not deps:
                self.labelDeps.setText("-")
            else:
                display_parts = []
                for dep in deps:
                    dep_info = next((p for p in self.plugins_metadata if p["id"] == dep), None)
                    if not dep_info:
                        display_parts.append(f"<span style='color: #f44336; font-weight: bold;'>{dep} ({tr('未インストール', 'PluginManager')})</span>")
                    elif not dep_info["enabled"]:
                        display_parts.append(f"<span style='color: #ff9800; font-weight: bold;'>{dep_info.get('name', dep)} ({tr('無効', 'PluginManager')})</span>")
                    else:
                        display_parts.append(f"<span style='color: green;'>{dep_info.get('name', dep)}</span>")
                self.labelDeps.setText(", ".join(display_parts))

        if self.textDescription:
            self.textDescription.setHtml(plugin_info.get("description", ""))

        self.current_selected_path = path
        if self.btnOpenFolder:
            self.btnOpenFolder.setEnabled(bool(path and os.path.exists(path)))

    def _open_plugin_folder(self):
        if self.current_selected_path and os.path.exists(self.current_selected_path):
            try:
                os.startfile(self.current_selected_path)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    tr("フォルダオープンエラー", "PluginManager"),
                    tr("フォルダを開けませんでした: {error}", "PluginManager").format(error=e)
                )

    def _create_new_plugin(self):
        dialog = CreatePluginDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_plugin_id = dialog.created_plugin_id
            # 新しいプラグインを読み込むためリロードし、新しく作成されたプラグインを選択状態にする
            self._load_plugins(select_id=new_plugin_id)

    def _on_accepted(self):
        # 最終的な並び順と有効無効状態の集計
        ordered_states = []
        search_text = self.lineSearch.text() if self.lineSearch else ""

        if not search_text:
            # 検索していない場合は、現在のリスト上の順番が最新の並び順
            for i in range(self.listPlugins.count()):
                item = self.listPlugins.item(i)
                p_id = item.data(Qt.UserRole)
                enabled = (item.checkState() == Qt.CheckState.Checked)
                ordered_states.append({"id": p_id, "enabled": enabled})
        else:
            # 検索フィルタ適用時は、現在の plugins_metadata の順番（チェック状態は itemChanged で同期済み）をそのまま使う
            for p in self.plugins_metadata:
                ordered_states.append({"id": p["id"], "enabled": p["enabled"]})

        # 変更があったかどうかのチェック
        has_changes = False
        if len(ordered_states) != len(self.original_states):
            has_changes = True
        else:
            for new, old in zip(ordered_states, self.original_states):
                if new["id"] != old["id"] or new["enabled"] != old["enabled"]:
                    has_changes = True
                    break

        if has_changes:
            if self.plugin_manager.save_plugin_enabled_states(ordered_states):
                self.has_changes = True
            else:
                QMessageBox.critical(
                    self,
                    tr("設定保存エラー", "PluginManager"),
                    tr("設定の保存に失敗しました。", "PluginManager")
                )
                return

        self.accept()
