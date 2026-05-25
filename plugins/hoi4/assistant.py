import os
import json
from PySide6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QTreeView, QListView, QMenu, QToolButton, QHBoxLayout, QLabel, QHeaderView
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QPoint, QEvent
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QAction
import core.api
from core.utils import load_svg_icon

class AssistantWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.base_dir = os.path.dirname(__file__)
        self.pinned_ids = []
        self.all_toolbox_items = {} # IDからアイテムデータを逆引きするためのキャッシュ
        self._hovered_nav_item_id = None
        self._tree_star_buttons = {}
        
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
            self.quickAccessLabel = self.container.findChild(QWidget, "quickAccessLabel")
            self.quickAccessList = self.container.findChild(QListView, "quickAccessList")
            
            # モデルの設定
            self.model = QStandardItemModel()
            if self.navigationTree:
                self.navigationTree.setModel(self.model)
                self.model.setColumnCount(2)
                self.navigationTree.setHeaderHidden(True)
                # カラム幅の調整（1列目を広げ、2列目を固定幅にする）
                self.navigationTree.setColumnWidth(1, 30)
                self._configure_navigation_tree_columns()
                self.navigationTree.setMouseTracking(True)
                self.navigationTree.viewport().setMouseTracking(True)
                self.navigationTree.viewport().installEventFilter(self)
                
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
            
            core.api.subscribe_event("project_path_changed", lambda _: self.load_toolbox())
            core.api.subscribe_event("file_saved", self.on_file_saved)
            core.api.subscribe_event("loc_changed", self.load_toolbox)

    def load_settings(self):
        """settings.json からピン留め情報を読み込む"""
        settings_path = os.path.join(self.base_dir, "settings.json")
        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            except Exception as e:
                print(f"Failed to load settings: {e}")

        if "pinned_ids" not in settings:
            settings["pinned_ids"] = [
                "create_decision",
                "create_event",
                "create_focus",
            ]

        self.pinned_ids = settings.get("pinned_ids", [])

        if not os.path.exists(settings_path):
            try:
                with open(settings_path, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"Failed to save settings: {e}")

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
            self.model.setColumnCount(2)
            self._configure_navigation_tree_columns()
            self._tree_star_buttons = {}
            self.all_toolbox_items = {}
            
            for nav_item in data.get("navigation", []):
                root_item = self.create_tree_item(nav_item)
                pin_item = QStandardItem()
                self.model.appendRow([root_item, pin_item])
                self.add_pin_button_to_tree(pin_item, nav_item.get("id"), nav_item)
                self.add_tree_items_recursive(root_item, nav_item.get("items", []))

            self.add_dynamic_decision_items()
            self.add_dynamic_achievement_items()
            self.add_dynamic_event_items()
            self.add_dynamic_localisation_items()
            
            if self.navigationTree:
                self.navigationTree.expandAll()
                self._configure_navigation_tree_columns()
            
            # クイックアクセスの更新
            self.update_quick_access_display()
                
        except Exception as e:
            print(f"Failed to load toolbox.json: {e}")

    def _configure_navigation_tree_columns(self):
        if not self.navigationTree:
            return

        header = self.navigationTree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.navigationTree.setColumnWidth(1, 24)

    def eventFilter(self, watched, event):
        if self.navigationTree and watched == self.navigationTree.viewport():
            if event.type() == QEvent.Type.MouseMove:
                index = self.navigationTree.indexAt(event.pos())
                if index.isValid() and index.column() == 1:
                    index = index.siblingAtColumn(0)
                item = self.model.itemFromIndex(index) if index.isValid() else None
                data = item.data(Qt.UserRole) if item else None
                hovered_id = data.get("id") if data else None
                if hovered_id != self._hovered_nav_item_id:
                    self._hovered_nav_item_id = hovered_id
                    self._update_tree_star_button_visibility()
            elif event.type() == QEvent.Type.Leave:
                if self._hovered_nav_item_id is not None:
                    self._hovered_nav_item_id = None
                    self._update_tree_star_button_visibility()
        elif isinstance(watched, QToolButton) and watched.property("navItemId"):
            if event.type() in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                hovered_id = watched.property("navItemId")
                if hovered_id != self._hovered_nav_item_id:
                    self._hovered_nav_item_id = hovered_id
                    self._update_tree_star_button_visibility()

        return super().eventFilter(watched, event)

    def _should_show_tree_star_placeholder(self, item_id, item_data=None):
        return item_id in self.pinned_ids or self._is_pinnable_item(item_id, item_data)
    def _is_pinnable_item(self, item_id, item_data=None):
        data = item_data or self.all_toolbox_items.get(item_id, {})
        return data.get("pinnable", False)

    def _update_tree_star_button_visibility(self):
        for item_id, btn in self._tree_star_buttons.items():
            btn.setVisible(item_id in self.pinned_ids or item_id == self._hovered_nav_item_id)

    def _sync_star_button(self, btn, item_id, tree_item=False):
        is_pinned = item_id in self.pinned_ids
        icon_name = "star.svg" if is_pinned else "star-outline.svg"
        icon_path = os.path.join(self.base_dir, "asset", "icons", icon_name)
        if os.path.exists(icon_path):
            btn.setIcon(load_svg_icon(icon_path, "#FFD700" if is_pinned else "#888888"))
        btn.setToolTip("ピン留めを解除" if is_pinned else "クイックアクセスに登録")
        if tree_item:
            btn.setVisible(is_pinned or item_id == self._hovered_nav_item_id)

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
            # 保存時はキャッシュを破棄して再走査を促す
            plugin = self.plugin
            if plugin and hasattr(plugin, "project_cache"):
                if "decisions" in plugin.project_cache:
                    del plugin.project_cache["decisions"]
            self.load_toolbox()
        
        achievements_root = os.path.normpath("common/achievements")
        if norm_rel_path == achievements_root or norm_rel_path.startswith(achievements_root + os.sep):
            # 実績ファイルの保存時もキャッシュを破棄
            plugin = self.plugin
            if plugin and hasattr(plugin, "project_cache"):
                if "achievements" in plugin.project_cache:
                    del plugin.project_cache["achievements"]
            self.load_toolbox()
        
        events_root = os.path.normpath("events")
        if norm_rel_path == events_root or norm_rel_path.startswith(events_root + os.sep):
            # イベントファイルの保存時もキャッシュを破棄
            plugin = self.plugin
            if plugin and hasattr(plugin, "project_cache"):
                if "events" in plugin.project_cache:
                    del plugin.project_cache["events"]
            self.load_toolbox()

    def add_dynamic_event_items(self):
        """MOD内のイベントをナビゲーションへ追加する"""
        events_item = self.find_tree_item_by_id("events_root")
        project_path = core.api.get_project_path()
        if not events_item or not project_path:
            return

        try:
            from plugins.hoi4.events.event_editor import EventParser
            plugin = self.plugin
            parser = EventParser(plugin)
            
            events = []
            if plugin and hasattr(plugin, "project_cache") and "events" in plugin.project_cache:
                events = parser.deserialize_events(plugin.project_cache["events"])
            else:
                events = parser.parse_project(project_path, plugin=self.plugin)
            
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
                
        except Exception as e:
            print(f"Failed to load event navigation: {e}")
            return

        events_by_file = {}
        for evt in events:
            if not evt.source_path:
                continue
            events_by_file.setdefault(evt.source_path, []).append(evt)

        for source_path in sorted(events_by_file.keys()):
            namespace = ""
            abs_path = source_path
            if not os.path.isabs(abs_path):
                abs_path = os.path.join(project_path, source_path)
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, "r", encoding="utf-8-sig") as f:
                        doc = parser.parse_document(abs_path, f.read())
                    namespace = doc.properties.get("add_namespace", "")
                except Exception as e:
                    print(f"Failed to parse event file {abs_path}: {e}")

            file_label = namespace or os.path.basename(source_path)
            file_data = {
                "id": f"event_file:{source_path}",
                "label": file_label,
                "icon": "event.svg",
                "action": "open_tab",
                "params": {"path": source_path, "editor_id": "event_editor", "target_id": "file_settings"},
            }
            file_item = self.create_tree_item(file_data)
            pin_item = QStandardItem()
            events_item.appendRow([file_item, pin_item])
            self.add_pin_button_to_tree(pin_item, file_data["id"], file_data)
            self.all_toolbox_items[file_data["id"]] = file_data

            seen_events = set()
            for evt in sorted(events_by_file[source_path], key=lambda a: a.event_id.lower()):
                if evt.event_id in seen_events:
                    continue
                seen_events.add(evt.event_id)

                # イベントの翻訳
                entry = None
                if registry:
                    _, entry = registry.search_key_status(f"{evt.event_id}.t")
                    if not entry:
                        _, entry = registry.search_key_status(evt.event_id)
                
                evt_label = entry.get("value") if entry else evt.event_id

                evt_data = {
                    "id": f"event:{evt.event_id}:{source_path}",
                    "label": evt_label,
                    "icon": "event.svg",
                    "action": "open_tab",
                    "params": {"path": source_path, "editor_id": "event_editor", "target_id": evt.event_id},
                }

                evt_tree_item = self.create_tree_item(evt_data)
                pin_item = QStandardItem()
                file_item.appendRow([evt_tree_item, pin_item])
                self.add_pin_button_to_tree(pin_item, evt_data["id"], evt_data)
                self.all_toolbox_items[evt_data["id"]] = evt_data

    def add_dynamic_localisation_items(self):
        """MOD内の翻訳ファイルをナビゲーションへ追加する"""
        loc_root_item = self.find_tree_item_by_id("localisation_root")
        project_path = core.api.get_project_path()
        if not loc_root_item or not project_path:
            return

        # MOD側のスキャン結果を取得して追加
        try:
            plugin = self.plugin
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
            if not registry:
                return
            
            # MOD側のスキャン結果を取得
            mod_files = [f for f in registry.file_registry if f.get("source") == "mod"]
        except Exception as e:
            print(f"Failed to load localisation navigation: {e}")
            return

        for file_info in sorted(mod_files, key=lambda f: f.get("filename", "").lower()):
            file_path = file_info.get("path")
            filename = file_info.get("filename")
            
            rel_path = os.path.relpath(file_path, project_path)

            file_data = {
                "id": f"localisation_file:{file_path}",
                "label": filename,  # ファイル名を表示
                "icon": "i18n.svg",
                "action": "open_tab",
                "params": {"path": rel_path, "editor_id": "localisation_editor"},
            }
            
            file_item = self.create_tree_item(file_data)
            pin_item = QStandardItem()
            loc_root_item.appendRow([file_item, pin_item])
            self.add_pin_button_to_tree(pin_item, file_data["id"], file_data)
            self.all_toolbox_items[file_data["id"]] = file_data

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
            plugin = self.plugin
            parser = DecisionParser(plugin)
            
            categories = []
            # キャッシュがあればそれを利用、なければパース
            if plugin and hasattr(plugin, "project_cache") and "decisions" in plugin.project_cache:
                categories = parser.deserialize_categories(plugin.project_cache["decisions"])
            else:
                categories = parser.parse_project(project_path, plugin=self.plugin)
            
            # ローカライズレジストリの取得
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
                
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            print(f"Failed to load decision navigation: {e}\n{err}")
            core.api.show_message(f"ナビゲーション読み込みエラー: {e}", 10000)
            return

        category_map = {}
        for category in categories:
            category_id = category.id
            category_path = category.source_path or self._category_navigation_path(category)
            if not category_path:
                continue
            
            if category_id not in category_map:
                category_map[category_id] = {
                    "category": category,
                    "source_path": category_path,
                    "decisions": {}
                }
            
            for decision in category.decisions:
                if not decision.source_path:
                    continue
                category_map[category_id]["decisions"][decision.id] = (decision, decision.source_path)

        for category_id in sorted(category_map.keys(), key=lambda k: k.lower()):
            group = category_map[category_id]
            category = group["category"]
            source_path = group["source_path"]
            
            status, entry = registry.search_key_status(category.id) if registry else ("not_found", None)
            category_label = entry.get("value") if entry else category.id
            
            category_data = {
                "id": f"decision_category:{category.id}:{source_path}",
                "label": category_label,
                "icon": "mail-checkmark-24-regular.svg",
                "action": "open_tab",
                "params": {"path": source_path, "editor_id": "decision_editor", "target_id": category.id},
            }
            category_item = self.create_tree_item(category_data)
            pin_item = QStandardItem()
            decisions_item.appendRow([category_item, pin_item])
            self.add_pin_button_to_tree(pin_item, category_data["id"], category_data)
            self.all_toolbox_items[category_data["id"]] = category_data

            for dec_id in sorted(group["decisions"].keys(), key=lambda k: k.lower()):
                decision, dec_source_path = group["decisions"][dec_id]
                status, entry = registry.search_key_status(decision.id) if registry else ("not_found", None)
                decision_label = entry.get("value") if entry else decision.id
                
                decision_data = {
                    "id": f"decision:{category.id}:{decision.id}:{dec_source_path}",
                    "label": decision_label,
                    "icon": "generic_decision.png",
                    "action": "open_tab",
                    "params": {"path": dec_source_path, "editor_id": "decision_editor", "target_id": decision.id},
                }
                decision_item = self.create_tree_item(decision_data)
                pin_item = QStandardItem()
                category_item.appendRow([decision_item, pin_item])
                self.add_pin_button_to_tree(pin_item, decision_data["id"], decision_data)
                self.all_toolbox_items[decision_data["id"]] = decision_data

    def add_dynamic_achievement_items(self):
        """MOD内の実績をナビゲーションへ追加する"""
        achievements_item = self.find_tree_item_by_id("achievements")
        project_path = core.api.get_project_path()
        if not achievements_item or not project_path:
            return

        try:
            from plugins.hoi4.achievement.achievement_editor import AchievementParser
            plugin = self.plugin
            parser = AchievementParser(plugin)
            
            achievements = []
            if plugin and hasattr(plugin, "project_cache") and "achievements" in plugin.project_cache:
                achievements = parser.deserialize_achievements(plugin.project_cache["achievements"])
            else:
                achievements = parser.parse_project(project_path, plugin=self.plugin)
            
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
                
        except Exception as e:
            print(f"Failed to load achievement navigation: {e}")
            return

        # 1. 実績をsource_path（ファイル）ごとにグループ化する
        achievements_by_file = {}
        for ach in achievements:
            if not ach.source_path:
                continue
            achievements_by_file.setdefault(ach.source_path, []).append(ach)

        # 2. ファイルごとに親子ツリーを構築
        for source_path in sorted(achievements_by_file.keys()):
            # 実ファイルからunique_idを抽出する
            unique_id = ""
            abs_path = source_path
            if not os.path.isabs(abs_path):
                abs_path = os.path.join(project_path, source_path)
            
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8-sig') as f:
                        content = f.read()
                    doc = parser.parse_document(abs_path, content)
                    unique_id = doc.properties.get("unique_id", "")
                except Exception as e:
                    print(f"Failed to parse achievement file {abs_path}: {e}")

            # 表示用ラベルの決定
            root_label = unique_id
            if registry and unique_id:
                _, root_entry = registry.search_key_status(unique_id)
                if root_entry and root_entry.get("value"):
                    root_label = root_entry.get("value")
            
            if not root_label:
                root_label = os.path.basename(source_path)

            # 親ノード（ファイル設定）の作成
            file_data = {
                "id": f"achievement_file:{source_path}",
                "label": root_label,
                "icon": "trophy-32.svg",
                "action": "open_tab",
                "params": {"path": source_path, "editor_id": "achievement_editor", "target_id": "file_settings"},
            }
            file_item = self.create_tree_item(file_data)
            pin_item = QStandardItem()
            achievements_item.appendRow([file_item, pin_item])
            self.add_pin_button_to_tree(pin_item, file_data["id"], file_data)
            self.all_toolbox_items[file_data["id"]] = file_data

            # 子ノード（実績個別）の追加
            seen_achievements = set()
            for ach in sorted(achievements_by_file[source_path], key=lambda a: a.id.lower()):
                if ach.id in seen_achievements:
                    continue
                seen_achievements.add(ach.id)

                entry = None
                if registry:
                    _, entry = registry.search_key_status(f"{ach.id}_NAME")
                    if not entry:
                        _, entry = registry.search_key_status(ach.id)
                
                ach_label = entry.get("value") if entry else ach.id

                ach_data = {
                    "id": f"achievement:{ach.id}:{source_path}",
                    "label": ach_label,
                    "icon": "trophy-32.svg",
                    "action": "open_tab",
                    "params": {"path": source_path, "editor_id": "achievement_editor", "target_id": ach.id},
                }
                ach_item = self.create_tree_item(ach_data)
                pin_item = QStandardItem()
                file_item.appendRow([ach_item, pin_item])
                self.add_pin_button_to_tree(pin_item, ach_data["id"], ach_data)
                self.all_toolbox_items[ach_data["id"]] = ach_data

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
                q_item = QStandardItem() # ラベルはカスタムウィジェット側で表示
                q_item.setEditable(False)
                q_item.setData(item_data, Qt.UserRole)
                self.quickModel.appendRow(q_item)
                self.add_item_widget_to_list(q_item, item_data)
        
        # 高さを項目数に合わせて調整
        if self.quickAccessList:
            count = self.quickModel.rowCount()
            if count == 0:
                self.quickAccessList.setFixedHeight(0)
                self.quickAccessList.setVisible(False)
                if hasattr(self, "quickAccessLabel") and self.quickAccessLabel:
                    self.quickAccessLabel.setVisible(False)
            else:
                self.quickAccessList.setVisible(True)
                if hasattr(self, "quickAccessLabel") and self.quickAccessLabel:
                    self.quickAccessLabel.setVisible(True)
                
                # 項目の高さから合計を計算
                total_height = 0
                for i in range(count):
                    # sizeHintForRow が -1 を返す場合があるため、デフォルト値を考慮
                    h = self.quickAccessList.sizeHintForRow(i)
                    if h <= 0:
                        h = 24 # デフォルトの高さ
                    total_height += h
                
                # 枠線分を追加
                total_height += self.quickAccessList.frameWidth() * 2
                self.quickAccessList.setFixedHeight(total_height)

    def add_tree_items_recursive(self, parent_item, items_data):
        """再帰的に項目を追加し、IDを持つ項目をキャッシュする"""
        for item_data in items_data:
            child_item = self.create_tree_item(item_data)
            pin_item = QStandardItem()
            parent_item.appendRow([child_item, pin_item])
            self.add_pin_button_to_tree(pin_item, item_data.get("id"), item_data)
            
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
        if index.column() == 1:
            index = index.siblingAtColumn(0)
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
                core.api.open_tab(file_path, editor_id, params)
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
        
        if index.column() == 1:
            index = index.siblingAtColumn(0)
            
        item = self.model.itemFromIndex(index)
        data = item.data(Qt.UserRole)
        item_id = data.get("id")
        action = data.get("action")
        
        # pinnable プロパティを持つ項目のみピン留め可能
        if not self._is_pinnable_item(item_id, data): return
        
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
        self.refresh_all_pin_buttons()

    def _refresh_tree_pin_buttons_recursive(self, parent_item):
        """再帰的にツリーのピン留めボタンの状態を更新する"""
        for row in range(parent_item.rowCount()):
            label_item = parent_item.child(row, 0)
            pin_item = parent_item.child(row, 1)
            if label_item and pin_item:
                data = label_item.data(Qt.UserRole)
                item_id = data.get("id") if data else None
                if item_id:
                    self.add_pin_button_to_tree(pin_item, item_id, data)
                
                # 子階層も更新
                self._refresh_tree_pin_buttons_recursive(label_item)

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

    def add_pin_button_to_tree(self, item, item_id, item_data=None):
        """ツリーの特定の項目にピン留めボタンを配置する"""
        if not item_id or not self.navigationTree: return

        if not self._should_show_tree_star_placeholder(item_id, item_data):
            self.navigationTree.setIndexWidget(item.index(), None)
            self._tree_star_buttons.pop(item_id, None)
            return

        existing_btn = self._tree_star_buttons.get(item_id)
        if existing_btn:
            self._sync_star_button(existing_btn, item_id, tree_item=True)
            return
        
        btn = self._create_star_button(item_id, tree_item=True)
        btn.setProperty("navItemId", item_id)
        btn.setMouseTracking(True)
        btn.installEventFilter(self)
        self._tree_star_buttons[item_id] = btn
        self.navigationTree.setIndexWidget(item.index(), btn)

    def add_item_widget_to_list(self, item, item_data):
        """リストの項目にカスタムウィジェット（ラベル＋ボタン）を配置する"""
        if not self.quickAccessList: return
        
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        
        # アイコン
        icon_label = QLabel()
        icon_name = item_data.get("icon")
        if icon_name:
            icon_path = os.path.join(self.base_dir, "asset", "icons", icon_name)
            if os.path.exists(icon_path):
                text_color = self.palette().color(self.foregroundRole()).name()
                icon_label.setPixmap(load_svg_icon(icon_path, text_color).pixmap(16, 16))
        layout.addWidget(icon_label)
        
        # ラベル
        label = QLabel(item_data.get("label", "Unknown"))
        layout.addWidget(label)
        layout.addStretch()
        
        # ピン留めボタン
        btn = self._create_star_button(item_data["id"])
        layout.addWidget(btn)
        
        item.setSizeHint(widget.sizeHint())
        self.quickAccessList.setIndexWidget(item.index(), widget)

    def _create_star_button(self, item_id, tree_item=False):
        """共通のスターボタンを作成する"""
        btn = QToolButton()
        btn.setFixedSize(20, 20)
        btn.setAutoRaise(True)
        btn.setCursor(Qt.PointingHandCursor)

        btn.clicked.connect(lambda: self.toggle_pin(item_id))
        self._sync_star_button(btn, item_id, tree_item)
        return btn

    def refresh_all_pin_buttons(self):
        """ツリー全体とリストのピン留めボタンの状態を更新する"""
        # ツリーの更新
        self._refresh_tree_pin_buttons_recursive(self.model.invisibleRootItem())
        self._update_tree_star_button_visibility()
        # リストは update_quick_access_display で再構築されるため不要
