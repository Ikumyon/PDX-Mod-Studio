import os
import json
from PySide6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QTreeView, QListView, QMenu
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QPoint
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QAction
import core.api
from core.utils import load_svg_icon

class AssistantWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_dir = os.path.dirname(__file__)
        self.pinned_ids = []
        self.all_toolbox_items = {} # IDからアイテムデータを逆引きするためのキャッシュ
        
        # UIのロード
        loader = QUiLoader()
        ui_path = os.path.join(self.base_dir, "assistant.ui")
        ui_file = QFile(ui_path)
        if ui_file.open(QFile.ReadOnly):
            self.container = loader.load(ui_file, self)
            ui_file.close()
            
            # 自身のレイアウトにロードしたUIを追加
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(self.container)
            
            # UI要素の取得
            self.header = self.container.findChild(QPushButton, "toolboxHeader")
            self.content = self.container.findChild(QWidget, "assistantContent")
            self.navigationTree = self.container.findChild(QTreeView, "navigationTree")
            self.quickAccessList = self.container.findChild(QListView, "quickAccessList")
            
            # モデルの設定
            self.model = QStandardItemModel()
            if self.navigationTree:
                self.navigationTree.setModel(self.model)
                self.navigationTree.setHeaderHidden(True)
                self.navigationTree.clicked.connect(self.on_item_clicked)
                # コンテキストメニューの設定
                self.navigationTree.setContextMenuPolicy(Qt.CustomContextMenu)
                self.navigationTree.customContextMenuRequested.connect(self.show_navigation_context_menu)
            
            self.quickModel = QStandardItemModel()
            if self.quickAccessList:
                self.quickAccessList.setModel(self.quickModel)
                self.quickAccessList.clicked.connect(self.on_quick_item_clicked)
                # コンテキストメニューの設定
                self.quickAccessList.setContextMenuPolicy(Qt.CustomContextMenu)
                self.quickAccessList.customContextMenuRequested.connect(self.show_quick_context_menu)

            # 設定とツールボックスの読み込み
            self.load_settings()
            self.load_toolbox()
            
            # シグナルの接続
            if self.header:
                self.header.setProperty("isHeader", True)
                self.header.clicked.connect(self.toggle_content)
                self.update_header_icon()
            
            core.api.register_project_path_handler(lambda _: self.load_toolbox())
            core.api.register_file_saved_handler(self.on_file_saved)

    def load_settings(self):
        """settings.json からピン留め情報を読み込む"""
        settings_path = os.path.join(self.base_dir, "settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.pinned_ids = settings.get("pinned_ids", [])
            except Exception as e:
                print(f"Failed to load settings: {e}")

    def save_settings(self):
        """ピン留め情報を settings.json に保存する"""
        settings_path = os.path.join(self.base_dir, "settings.json")
        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            except Exception: pass
        
        settings["pinned_ids"] = self.pinned_ids
        try:
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def load_toolbox(self):
        """toolbox.json を読み込んでツリーとクイックアクセスを構築する"""
        json_path = os.path.join(self.base_dir, "toolbox.json")
        if not os.path.exists(json_path): return
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.model.clear()
            self.all_toolbox_items = {}
            
            for nav_item in data.get("navigation", []):
                root_item = self.create_tree_item(nav_item)
                self.model.appendRow(root_item)
                self.add_tree_items_recursive(root_item, nav_item.get("items", []))

            self.add_dynamic_decision_items()
            
            if self.navigationTree:
                self.navigationTree.expandAll()
            
            # クイックアクセスの更新
            self.update_quick_access_display()
                
        except Exception as e:
            print(f"Failed to load toolbox.json: {e}")

    def on_file_saved(self, file_path):
        """ディシジョン関連ファイルの保存時にナビゲーションを読み直す"""
        project_path = core.api.get_project_path()
        if not project_path or not file_path:
            return

        try:
            rel_path = os.path.relpath(file_path, project_path)
        except ValueError:
            return

        decisions_root = os.path.normpath("common/decisions")
        norm_rel_path = os.path.normpath(rel_path)
        if norm_rel_path == decisions_root or norm_rel_path.startswith(decisions_root + os.sep):
            self.load_toolbox()

    def add_dynamic_decision_items(self):
        """MOD内のディシジョンをカテゴリ別にナビゲーションへ追加する"""
        decisions_item = self.find_tree_item_by_id("decisions")
        project_path = core.api.get_project_path()
        if not decisions_item or not project_path:
            return

        decisions_dir = os.path.join(project_path, "common", "decisions")
        if not os.path.isdir(decisions_dir):
            return

        try:
            from plugins.hoi4.decisions.decision_editor import DecisionParser
            categories = DecisionParser().parse_project(project_path)
        except Exception as e:
            print(f"Failed to load decision navigation: {e}")
            return

        for category in sorted(categories, key=lambda cat: cat.id.lower()):
            category_path = self._category_navigation_path(category)
            category_data = {
                "id": f"decision_category:{category.id}",
                "label": category.id,
                "icon": "mail-checkmark-24-regular.svg",
                "action": "open_tab" if category_path else "",
                "params": {"path": category_path, "editor_id": "decision_editor"} if category_path else {},
            }
            category_item = self.create_tree_item(category_data)
            decisions_item.appendRow(category_item)
            self.all_toolbox_items[category_data["id"]] = category_data

            seen_decisions = set()
            for decision in sorted(category.decisions, key=lambda dec: (dec.id.lower(), dec.source_path or "")):
                decision_key = (decision.id, os.path.normcase(os.path.abspath(decision.source_path or "")))
                if decision_key in seen_decisions:
                    continue
                seen_decisions.add(decision_key)

                decision_data = {
                    "id": f"decision:{category.id}:{decision.id}:{decision.source_path or ''}",
                    "label": decision.id,
                    "icon": "generic_decision.png",
                    "action": "open_tab",
                    "params": {"path": decision.source_path, "editor_id": "decision_editor"},
                }
                decision_item = self.create_tree_item(decision_data)
                category_item.appendRow(decision_item)
                self.all_toolbox_items[decision_data["id"]] = decision_data

    def _category_navigation_path(self, category):
        if category.source_path:
            return category.source_path
        for decision in category.decisions:
            if decision.source_path:
                return decision.source_path
        return ""

    def find_tree_item_by_id(self, item_id):
        for row in range(self.model.rowCount()):
            found = self._find_tree_item_by_id(self.model.item(row), item_id)
            if found:
                return found
        return None

    def _find_tree_item_by_id(self, item, item_id):
        if not item:
            return None
        data = item.data(Qt.UserRole) or {}
        if data.get("id") == item_id:
            return item
        for row in range(item.rowCount()):
            found = self._find_tree_item_by_id(item.child(row), item_id)
            if found:
                return found
        return None

    def update_quick_access_display(self):
        """ピン留めされたIDに基づきクイックアクセス一覧を更新する"""
        self.quickModel.clear()
        for item_id in self.pinned_ids:
            item_data = self.all_toolbox_items.get(item_id)
            if item_data:
                q_item = self.create_tree_item(item_data)
                self.quickModel.appendRow(q_item)

    def add_tree_items_recursive(self, parent_item, items_data):
        """再帰的に項目を追加し、IDを持つ項目をキャッシュする"""
        for item_data in items_data:
            child_item = self.create_tree_item(item_data)
            parent_item.appendRow(child_item)
            
            item_id = item_data.get("id")
            if item_id:
                self.all_toolbox_items[item_id] = item_data
                
            if "items" in item_data:
                self.add_tree_items_recursive(child_item, item_data["items"])

    def create_tree_item(self, item_data):
        """JSONデータからツリー項目を作成する"""
        item = QStandardItem(item_data.get("label", "Unknown"))
        item.setEditable(False)
        item.setData(item_data, Qt.UserRole)
        
        icon_name = item_data.get("icon")
        if icon_name:
            icon_path = os.path.join(self.base_dir, "asset", "icons", icon_name)
            if os.path.exists(icon_path):
                if icon_path.lower().endswith(".svg"):
                    text_color = self.palette().color(self.foregroundRole()).name()
                    item.setIcon(load_svg_icon(icon_path, text_color))
                else:
                    item.setIcon(QIcon(icon_path))
        
        return item

    def on_item_clicked(self, index):
        item = self.model.itemFromIndex(index)
        self.execute_item_action(item)

    def on_quick_item_clicked(self, index):
        item = self.quickModel.itemFromIndex(index)
        self.execute_item_action(item)

    def execute_item_action(self, item):
        """アイテムに設定されたアクションを実行する"""
        data = item.data(Qt.UserRole)
        if not data: return
            
        action = data.get("action")
        params = data.get("params", {})
        
        if action == "open_folder":
            folder_path = params.get("path")
            project_path = core.api.get_project_path()
            if project_path and folder_path:
                full_path = os.path.join(project_path, folder_path)
                if os.path.exists(full_path):
                    core.api.show_message(f"フォルダを表示します: {folder_path}")
                else:
                    core.api.show_message(f"フォルダが見つかりません: {folder_path}", 5000)
        elif action == "open_tab":
            file_path = params.get("path")
            editor_id = params.get("editor_id")
            if file_path and not os.path.isabs(file_path):
                project_path = core.api.get_project_path()
                if project_path:
                    file_path = os.path.join(project_path, file_path)
            if file_path and os.path.exists(file_path):
                core.api.open_tab(file_path, editor_id)
        elif action == "open_untitled_tab":
            name = params.get("name", "Untitled")
            content = params.get("content", "")
            editor_id = params.get("editor_id", core.api.BUILTIN_TEXT_EDITOR_ID)
            core.api.open_untitled_tab(name, content, editor_id)
        elif action == "show_message":
            core.api.show_message(params.get("text", ""))

    def show_navigation_context_menu(self, pos: QPoint):
        """ナビゲーションツリーの右クリックメニュー"""
        index = self.navigationTree.indexAt(pos)
        if not index.isValid(): return
        
        item = self.model.itemFromIndex(index)
        data = item.data(Qt.UserRole)
        item_id = data.get("id")
        action = data.get("action")
        
        # IDがあり、かつアクションを持つ項目（末端の作成項目など）のみピン留め可能
        if not item_id or not action: return
        
        menu = QMenu(self)
        if item_id in self.pinned_ids:
            act = QAction("クイックアクセスから解除", self)
            act.triggered.connect(lambda: self.toggle_pin(item_id))
        else:
            act = QAction("クイックアクセスに登録", self)
            act.triggered.connect(lambda: self.toggle_pin(item_id))
        
        menu.addAction(act)
        menu.exec(self.navigationTree.mapToGlobal(pos))

    def show_quick_context_menu(self, pos: QPoint):
        """クイックアクセスの右クリックメニュー"""
        index = self.quickAccessList.indexAt(pos)
        if not index.isValid(): return
        
        item = self.quickModel.itemFromIndex(index)
        data = item.data(Qt.UserRole)
        item_id = data.get("id")
        
        menu = QMenu(self)
        act = QAction("解除", self)
        act.triggered.connect(lambda: self.toggle_pin(item_id))
        menu.addAction(act)
        menu.exec(self.quickAccessList.mapToGlobal(pos))

    def toggle_pin(self, item_id):
        """ピン留め状態を切り替えて保存する"""
        if item_id in self.pinned_ids:
            self.pinned_ids.remove(item_id)
        else:
            self.pinned_ids.append(item_id)
        
        self.save_settings()
        self.update_quick_access_display()

    def update_header_icon(self):
        """ヘッダーのアイコンをコンテンツの表示状態に合わせて更新する"""
        if not self.header or not self.content: return
        
        # isVisible()はウィジェットが実際に表示されるまでFalseを返すため、isHidden()を使用する
        is_visible = not self.content.isHidden()
        icon_name = "chevron-down.svg" if is_visible else "chevron-right.svg"
        icon_path = os.path.join(self.base_dir, "asset", "icons", icon_name)
        
        if os.path.exists(icon_path):
            text_color = self.palette().color(self.foregroundRole()).name()
            self.header.setIcon(load_svg_icon(icon_path, text_color))

    def toggle_content(self):
        """コンテンツエリアの表示/非表示を切り替える"""
        if self.content:
            # 論理的な表示状態に基づいて切り替える
            is_visible = not self.content.isHidden()
            self.content.setVisible(not is_visible)
            self.update_header_icon()
