import os
import json
from PySide6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QTreeView
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QPixmap
import core.api
from core.utils import load_svg_icon

# 各種パーサーをインポート（失敗した場合は None）
try:
    from plugins.hoi4.decisions.decision_editor import DecisionParser
except ImportError:
    DecisionParser = None

try:
    from plugins.hoi4.events.event_editor import EventParser
except ImportError:
    EventParser = None

class AssistantWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_dir = os.path.dirname(__file__)
        self.decision_parser = DecisionParser() if DecisionParser else None
        self.event_parser = EventParser() if EventParser else None
        
        self.decision_item = None # 動的項目を追加するための親項目を保持
        self.event_item = None
        
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
            
            # モデルの設定
            self.model = QStandardItemModel()
            if self.navigationTree:
                self.navigationTree.setModel(self.model)
                self.navigationTree.setHeaderHidden(True)
                self.navigationTree.clicked.connect(self.on_item_clicked)
            
            # JSONの読み込みと項目の追加
            self.load_toolbox()
            
            # シグナルの接続
            if self.header:
                # カスタムプロパティ（スタイリング用）
                self.header.setProperty("isHeader", True)
                self.header.clicked.connect(self.toggle_content)
            
            # プロジェクトの状態変化を監視
            core.api.register_project_path_handler(lambda _: self.load_toolbox())
            core.api.register_file_saved_handler(self.on_file_saved)
                
    def on_file_saved(self, file_path):
        """ファイル保存時に、関連ファイルであればツリーを更新する"""
        p = file_path.replace("\\", "/")
        if "decisions" in p or "events" in p:
            self.load_toolbox()

    def load_toolbox(self):
        """toolbox.json を読み込んでツリーを構築し、動的な項目を追加する"""
        json_path = os.path.join(self.base_dir, "toolbox.json")
        if not os.path.exists(json_path): return
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.model.clear()
            self.decision_item = None
            self.event_item = None
            
            for nav_item in data.get("navigation", []):
                parent_item = self.create_tree_item(nav_item)
                self.model.appendRow(parent_item)
                
                # 子項目の追加
                for sub_item in nav_item.get("items", []):
                    child_item = self.create_tree_item(sub_item)
                    parent_item.appendRow(child_item)
                    
                    # 再帰的な子要素（items）の読み込みをサポート
                    if "items" in sub_item:
                        for sub_sub_item in sub_item["items"]:
                            child_item.appendRow(self.create_tree_item(sub_sub_item))

                    # 特定のノードを動的追加用に保持
                    node_id = sub_item.get("id")
                    if node_id == "decisions":
                        self.decision_item = child_item
                    elif node_id == "events_root":
                        self.event_item = child_item
            
            # 動的な項目の追加
            self.add_dynamic_items()
            if self.navigationTree:
                self.navigationTree.expandAll()
                
        except Exception as e:
            print(f"Failed to load toolbox.json: {e}")

    def _clear_dynamic_children(self, parent_item):
        """「＋」項目以外の動的な子要素を削除する"""
        if not parent_item: return
        for row in reversed(range(parent_item.rowCount())):
            child = parent_item.child(row)
            if child and not child.text().startswith("＋"):
                parent_item.removeRow(row)

    def _add_new_item_shortcut(self, parent, label, name, content, editor_id=core.api.BUILTIN_TEXT_EDITOR_ID):
        """「＋ 新規作成」ショートカット項目を生成して追加する"""
        item = QStandardItem(label)
        item.setEditable(False)
        item.setForeground(Qt.GlobalColor.gray)
        item.setData({
            "action": "open_untitled_tab", 
            "params": {"name": name, "content": content, "editor_id": editor_id}
        }, Qt.UserRole)
        parent.appendRow(item)

    def add_dynamic_items(self):
        """プロジェクトを解析して動的なナビゲーション項目を追加する"""
        project_path = core.api.get_project_path()
            
        # 1. ディシジョンカテゴリの追加
        if self.decision_item and self.decision_parser:
            self._clear_dynamic_children(self.decision_item)
            
            if project_path:
                try:
                    categories = self.decision_parser.parse_project(project_path)
                    added_ids = set()
                    for cat in reversed(categories): # 上に挿入するため逆順
                        if cat.id in added_ids: continue
                        cat_item = QStandardItem(cat.id)
                        cat_item.setEditable(False)
                        icon_path = os.path.join(self.base_dir, "asset", "icons", "mail-checkmark-24-regular.svg")
                        if os.path.exists(icon_path):
                            text_color = self.palette().color(self.foregroundRole()).name()
                            cat_item.setIcon(load_svg_icon(icon_path, text_color))
                        cat_item.setData({"id": cat.id, "action": "open_tab", "params": {"path": cat.source_path}}, Qt.UserRole)
                        
                        self.decision_item.insertRow(0, cat_item)
                        
                        # カテゴリ内の「＋ 新規ディシジョン」
                        template = "\n\tnew_decision_id = {\n\t\t# ここに処理を記述\n\t}\n"
                        self._add_new_item_shortcut(cat_item, "＋ 新規ディシジョン...", f"New Decision ({cat.id})", template, "decision_editor")
                        added_ids.add(cat.id)
                except Exception as e:
                    print(f"Failed to add dynamic decisions: {e}")

        # 2. イベントの追加
        if self.event_item and self.event_parser:
            self._clear_dynamic_children(self.event_item)
            if project_path:
                try:
                    self.add_dynamic_events(project_path)
                except Exception as e:
                    print(f"Failed to add dynamic events: {e}")

    def add_dynamic_events(self, project_path):
        """プロジェクト内のイベントをスキャンし、ネームスペース単位で追加する"""
        events_dir = os.path.join(project_path, "events")
        if not os.path.exists(events_dir): return
            
        namespaces = {}
        for root, _, files in os.walk(events_dir):
            for file in files:
                if not file.endswith(".txt"): continue
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    doc = self.event_parser.parse_document(path, content)
                    ns = doc.properties.get("add_namespace", "unknown_namespace")
                    if ns not in namespaces:
                        namespaces[ns] = {"events": [], "path": path}
                    for ev in doc.events:
                        namespaces[ns]["events"].append({"id": ev.id, "path": path})
                except Exception: continue

        # 挿入位置を調整するために逆順で処理
        ns_list = list(namespaces.items())
        for ns, ns_data in reversed(ns_list):
            ns_item = QStandardItem(ns)
            ns_item.setEditable(False)
            icon_path = os.path.join(self.base_dir, "asset", "icons", "event.svg")
            if os.path.exists(icon_path):
                text_color = self.palette().color(self.foregroundRole()).name()
                ns_item.setIcon(load_svg_icon(icon_path, text_color))
            ns_item.setData({"id": ns, "action": "open_tab", "params": {"path": ns_data["path"]}}, Qt.UserRole)
            self.event_item.insertRow(0, ns_item)
            
            for ev_data in ns_data["events"]:
                ev_item = QStandardItem(ev_data["id"])
                ev_item.setEditable(False)
                ev_item.setData({"id": ev_data["id"], "action": "open_tab", "params": {"path": ev_data["path"]}}, Qt.UserRole)
                ns_item.appendRow(ev_item)
            
            # ネームスペース末尾に「新規イベント追加」項目
            template = f"\ncountry_event = {{\n\tid = {ns}.xxx\n\ttitle = \"Event Title\"\n\tdesc = \"Event Description\"\n\tpicture = GFX_report_event_generic_read_write\n\n\tis_triggered_only = yes\n\n\toption = {{\n\t\tname = \"OK\"\n\t}}\n}}\n"
            self._add_new_item_shortcut(ns_item, "＋ 新規イベント...", f"New Event ({ns})", template, "event_editor")

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
        """項目クリック時のアクション処理"""
        item = self.model.itemFromIndex(index)
        data = item.data(Qt.UserRole)
        if not data:
            return
            
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
            if file_path and os.path.exists(file_path):
                core.api.open_tab(file_path)
        elif action == "open_untitled_tab":
            name = params.get("name", "Untitled")
            content = params.get("content", "")
            editor_id = params.get("editor_id", core.api.BUILTIN_TEXT_EDITOR_ID)
            core.api.open_untitled_tab(name, content, editor_id)
        elif action == "show_message":
            core.api.show_message(params.get("text", ""))

    def toggle_content(self):
        """コンテンツエリアの表示/非表示を切り替える"""
        if self.content:
            self.content.setVisible(not self.content.isVisible())
