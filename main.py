import sys
import os
import yaml
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QDockWidget, 
    QStackedWidget, QWidget, QTabBar, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox, QFileSystemModel, QTreeView,
    QMenu, QTableView, QLineEdit, QPushButton, QGraphicsView,
    QListView, QLabel, QComboBox, QSizePolicy, QToolBar
)
from PySide6.QtGui import QAction, QPainter
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QTranslator, QCoreApplication, QModelIndex, QSize
from PySide6.QtGui import QAction, QPainter, QPixmap, QStandardItemModel, QStandardItem, QIcon
import shutil

# コアロジックのインポート
from core.project import ProjectManager
from app.resource_table_model import ResourceTableModel
from core.validator import ValidationEngine
from app.log_table_model import LogTableModel
from core.dependency_analyzer import DependencyAnalyzer
from app.graph_scene import DependencyGraphScene
from app.proposal_list_model import ProposalListModel, ProposalItem
from core.ai_provider import StructuredAIProvider
from core.context_builder import ContextBuilder
from core.localisation_manager import LocalisationManager
from app.localisation_table_model import LocalisationTableModel
from core.exporter import JsonExporter

# フォームビルダーのインポート
from app.form_builder import FormBuilder

class CustomUiLoader(QUiLoader):
    """QTabBarなどの標準ウィジェットが読み込めない問題を解決するためのカスタムローダー"""
    def createWidget(self, className, parent=None, name=""):
        if className == "QTabBar":
            widget = QTabBar(parent)
            widget.setObjectName(name)
            return widget
        return super().createWidget(className, parent, name)

class ModStudioApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.loader = CustomUiLoader()
        
        # 翻訳のセットアップ
        self.translator = QTranslator()
        self.base_path = Path(__file__).parent
        self.translations_path = self.base_path / "data" / "translations"
        
        # ja_JP.qm があればロード
        if self.translator.load("ja_JP.qm", str(self.translations_path)):
            self.app.installTranslator(self.translator)
        
        self.ui_path = self.base_path / "ui"
        self.dock_path = self.ui_path / "docks"
        self.workspace_path = self.ui_path / "workspaces"
        self.profiles_path = self.base_path / "profiles"
        self.editor_path = self.ui_path / "editors"
        self.icons_path = self.base_path / "assets" / "icons"
        self.styles_path = self.base_path / "assets" / "styles"
        
        # スキーマとビルダーの保持
        self.schemas = {}
        self.builders = {} # workspace_widget -> FormBuilder
        self.table_models = {} # workspace_widget -> ResourceTableModel
        self.active_files = {} # workspace_widget -> Path
        self.docks = [] # 追加: ドックのリスト
        self._connected_slots = set()
        
        # プロジェクト管理
        self.project_manager = ProjectManager()
        self.validator = ValidationEngine(self.project_manager, self.schemas)
        self.log_model = LogTableModel()
        self.dependency_analyzer = DependencyAnalyzer(self.project_manager, self.schemas)
        self.graph_scene = DependencyGraphScene()
        self.proposal_model = ProposalListModel()
        self.ai_provider = StructuredAIProvider()
        self.context_builder = ContextBuilder(self.project_manager, self.schemas)
        self.loc_manager = LocalisationManager(self.project_manager.project_root)
        self.loc_model = LocalisationTableModel(self.loc_manager)
        self.loc_manager.load_all()
        self.exporter = JsonExporter(self.project_manager)
        
        # 1. メインウィンドウの読み込み
        self.main_window = self._load_ui(self.ui_path / "main_window.ui")
        if not self.main_window:
            sys.exit(-1)
            
        # UIコンポーネントの参照取得
        self.main_tab_bar = self.main_window.findChild(QTabBar, "mainTabBar")
        self.central_stack = self.main_window.findChild(QStackedWidget, "centralStack")
        
        # 2. ドックUIのセットアップ
        self.setup_docks()
        self.setup_logs()
        
        # 4. プロジェクトツリーのセットアップ
        self.setup_project_tree()
        
        # 5. メニューアクションの接続
        self.setup_actions()
        
        self.main_window.showMaximized()


    def _load_ui(self, path):
        """UIファイルをロードしてウィジェットを返す"""
        ui_file = QFile(str(path))
        if not ui_file.open(QFile.ReadOnly):
            print(f"UIファイルを開けません: {path} - {ui_file.errorString()}")
            return None
        widget = self.loader.load(ui_file)
        ui_file.close()
        return widget

    def setup_docks(self):
        """ドックパネルをロードしてメインウィンドウに追加する"""
        self.docks = []
        # (UIファイル名, 配置エリア, アイコンファイル名)
        dock_configs = [
            ("project_tree_dock.ui", Qt.LeftDockWidgetArea, "folder-open.svg"),
            ("ai_assistant_dock.ui", Qt.RightDockWidgetArea, "lightbulb-filament-48.svg"),
            ("property_dock.ui", Qt.RightDockWidgetArea, "military-medal.svg"),
            ("proposal_queue_dock.ui", Qt.BottomDockWidgetArea, "flag.svg"),
            ("log_dock.ui", Qt.BottomDockWidgetArea, "data-area-20.svg"),
        ]
        
        # サイドバー（ツールバー）の保持用
        self.sidebars = {}

        for ui_file, area, icon_file in dock_configs:
            dock = self._load_ui(self.dock_path / ui_file)
            if dock:
                self.main_window.addDockWidget(area, dock)
                self.docks.append(dock)
                
                # サイドバーを取得または作成
                sidebar_area = self._get_toolbar_area(area)
                if sidebar_area not in self.sidebars:
                    self.sidebars[sidebar_area] = self._create_sidebar(sidebar_area)
                
                sidebar = self.sidebars[sidebar_area]
                
                # ドックのトグルアクションを設定
                action = dock.toggleViewAction()
                icon_path = self.icons_path / icon_file
                if icon_path.exists():
                    action.setIcon(QIcon(str(icon_path)))
                
                sidebar.addAction(action)

                # 特定のドックの初期化
                if ui_file == "proposal_queue_dock.ui":
                    self.setup_proposal_queue(dock)
                elif ui_file == "ai_assistant_dock.ui":
                    self.setup_ai_assistant(dock)
                elif ui_file == "localisation_workspace.ui":
                    self.setup_localisation_workspace(dock)

    def _get_toolbar_area(self, dock_area):
        """ドックエリアに対応するツールバーエリアを返す"""
        mapping = {
            Qt.LeftDockWidgetArea: Qt.LeftToolBarArea,
            Qt.RightDockWidgetArea: Qt.RightToolBarArea,
            Qt.BottomDockWidgetArea: Qt.BottomToolBarArea,
            Qt.TopDockWidgetArea: Qt.TopToolBarArea,
        }
        return mapping.get(dock_area, Qt.LeftToolBarArea)

    def _create_sidebar(self, area):
        """スリムなサイドバー（QToolBar）を作成してメインウィンドウに追加する"""
        sidebar = QToolBar("Sidebar")
        sidebar.setMovable(False)
        sidebar.setFloatable(False)
        sidebar.setIconSize(QSize(24, 24))
        sidebar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        
        # 向きの設定
        if area in [Qt.LeftToolBarArea, Qt.RightToolBarArea]:
            sidebar.setOrientation(Qt.Vertical)
        else:
            sidebar.setOrientation(Qt.Horizontal)
            
        # スタイリング (スリムでダークな外観)
        sidebar.setStyleSheet("""
            QToolBar {
                background-color: #2b2b2b;
                border: none;
                spacing: 10px;
                padding: 5px;
            }
            QToolButton {
                background-color: transparent;
                border-radius: 4px;
                padding: 4px;
            }
            QToolButton:checked {
                background-color: #404040;
                border-left: 2px solid #007acc;
            }
            QToolButton:hover {
                background-color: #3a3a3a;
            }
        """)
        
        self.main_window.addToolBar(area, sidebar)
        return sidebar



    def load_schemas(self, schemas_dir):
        """スキーマ定義をディレクトリから読み込む"""
        if not schemas_dir.exists():
            return
            
        print("スキーマをロード中...")
        for schema_file in schemas_dir.glob("*.yaml"):
            try:
                with open(schema_file, 'r', encoding='utf-8') as f:
                    schema_data = yaml.safe_load(f)
                    res_type = schema_data.get('resource_type')
                    if res_type:
                        self.schemas[res_type] = schema_data
                        print(f" - スキーマを登録しました: {res_type} ({schema_data.get('label')})")
            except Exception as e:
                print(f"スキーマファイル {schema_file.name} の読み込みに失敗しました: {e}")

    def add_workspace(self, title, ui_filename, sub_tabs_info=None, icon_name=None):
        """タイトルとUIファイルを指定してワークスペースを追加。サブタブがあれば構築。"""
        widget = self._load_ui(self.workspace_path / ui_filename)
        if widget:
            self.central_stack.addWidget(widget)
            
            if icon_name:
                icon_path = self.icons_path / icon_name
                if icon_path.exists():
                    self.main_tab_bar.addTab(QIcon(str(icon_path)), title)
                else:
                    self.main_tab_bar.addTab(title)
            else:
                self.main_tab_bar.addTab(title)
            
            if sub_tabs_info:
                self.setup_multi_resource_workspace(widget, sub_tabs_info)
                
            # 依存関係ワークスペースの特別処理
            if ui_filename == "dependency_workspace.ui":
                self.setup_dependency_workspace(widget)
            elif ui_filename == "asset_workspace.ui":
                self.setup_asset_workspace(widget)

    def setup_multi_resource_workspace(self, workspace_widget, sub_tabs_info):
        """ワークスペース内に複数のサブタブ（リソースタイプ）を構築する"""
        sub_tab_bar = workspace_widget.findChild(QTabBar, "subTabBar")
        editor_stack = workspace_widget.findChild(QStackedWidget, "editorStack")
        if not sub_tab_bar or not editor_stack:
            return
            
        # 既存のタブとページをクリア (emptyPage以外)
        while sub_tab_bar.count() > 0:
            sub_tab_bar.removeTab(0)
        while editor_stack.count() > 1:
            page = editor_stack.widget(1)
            editor_stack.removeWidget(page)
            page.deleteLater()
            
        # サブタブ情報の保持
        workspace_widget.setProperty("sub_tabs_info", sub_tabs_info)
        
        for sub_info in sub_tabs_info:
            label = sub_info.get('label', '無題')
            sub_tab_bar.addTab(label)
            
            # 各サブタブ用のコンテナページを作成
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            
            # 内部にさらに Stack を置いて一覧と編集を切り替えられるようにする
            inner_stack = QStackedWidget()
            inner_stack.setObjectName("innerEditorStack")
            page_layout.addWidget(inner_stack)
            
            editor_stack.addWidget(page)
            
            # 初期化（最初のタブだけ、または遅延初期化）
            schema_id = sub_info.get('resource_type') or sub_info.get('schema')
            if schema_id:
                schema = self.schemas.get(schema_id)
                if schema:
                    self.setup_resource_editors(inner_stack, schema, workspace_widget)

        # サブタブ切り替えの接続
        sub_tab_bar.currentChanged.connect(lambda idx: editor_stack.setCurrentIndex(idx + 1))
        
        if sub_tab_bar.count() > 0:
            sub_tab_bar.setCurrentIndex(0)
            editor_stack.setCurrentIndex(1)

    def setup_resource_editors(self, inner_stack, schema, workspace_widget):
        """スキーマの editor 指定に合わせてリソースエディタを作成する。"""
        editor = schema.get("editor", "form")
        if editor == "table":
            self._add_table_resource_editor(inner_stack, schema, workspace_widget)
        elif editor == "graph":
            self._add_graph_resource_editor(inner_stack, schema)
        else:
            self._add_form_resource_editor(inner_stack, schema)

        if inner_stack.count() > 0:
            inner_stack.setCurrentIndex(0)

    def _add_table_resource_editor(self, inner_stack, schema, workspace_widget):
        table_editor = self._load_ui(self.editor_path / "generic_table_editor.ui")
        if table_editor:
            inner_stack.addWidget(table_editor)
            
            model = ResourceTableModel(schema, self.project_manager)
            table_view = table_editor.findChild(QTableView, "tableView")
            if table_view:
                table_view.setModel(model)
                table_view.horizontalHeader().setStretchLastSection(True)
                table_view.setSelectionBehavior(QTableView.SelectRows)
                table_view.setSelectionMode(QTableView.SingleSelection)
                table_view.doubleClicked.connect(lambda index: self._on_table_row_selected_v2(inner_stack, workspace_widget, index))
            
            # モデルを管理対象に追加 (キーを工夫する必要がある)
            self.table_models[inner_stack] = model 
            model.load_data()
            
            # 検索
            search_edit = table_editor.findChild(QLineEdit, "tableSearchEdit")
            if search_edit:
                search_edit.textChanged.connect(model.filter)

    def _add_form_resource_editor(self, inner_stack, schema):
        form_editor = self._load_ui(self.editor_path / "generic_form_editor.ui")
        if form_editor:
            inner_stack.addWidget(form_editor)
            
            form_layout = form_editor.findChild(QVBoxLayout, "formLayout")
            builder = FormBuilder(form_layout, self.project_manager, self.schemas)
            builder.build(schema)
            self.builders[inner_stack] = builder
            
            # 保存ボタン
            save_btn = form_editor.findChild(QWidget, "saveButton")
            if save_btn:
                save_btn.clicked.connect(lambda: self.save_workspace_data_v2(inner_stack, schema))

    def _add_graph_resource_editor(self, inner_stack, schema):
        graph_editor = self._load_ui(self.editor_path / "generic_graph_editor.ui")
        if graph_editor:
            graph_editor.setProperty("resource_type", schema.get("resource_type"))
            inner_stack.addWidget(graph_editor)

    def _on_table_row_selected_v2(self, inner_stack, workspace_widget, index):
        """内側スタックでの行選択時の処理"""
        model = self.table_models.get(inner_stack)
        if not model: return
        
        path = model.get_path(index.row())
        if path:
            res_type, data = self.project_manager.load_resource(path)
            builder = self.builders.get(inner_stack)
            if builder and data:
                builder.set_data(data)
                self.active_files[inner_stack] = path
                inner_stack.setProperty("resource_type", res_type)
                
                # 編集画面へ切り替え (index 1)
                inner_stack.setCurrentIndex(1)

    def save_workspace_data_v2(self, inner_stack, schema):
        """内側スタックでのデータ保存"""
        builder = self.builders.get(inner_stack)
        file_path = self.active_files.get(inner_stack)
        if builder:
            res_type = inner_stack.property("resource_type") or schema['resource_type']
            data = builder.get_data()
            if not file_path:
                file_path = self._resource_path_for_data(schema, data)
                self.active_files[inner_stack] = file_path
            self.project_manager.save_resource(file_path, res_type, data)
            self.main_window.statusBar().showMessage(f"保存しました: {file_path.name}", 3000)
            
            # テーブルモデルの更新
            model = self.table_models.get(inner_stack)
            if model:
                model.load_data()
            
            # 一覧に戻るかはお好み。ここでは戻らない。

    def _resource_path_for_data(self, schema, data):
        """新規保存時に schema と id から保存先JSONパスを作る。"""
        resource_type = schema.get("resource_type", "resource")
        resource_id = str(data.get("id") or resource_type)
        safe_id = "".join(
            char if char.isalnum() or char in "._-" else "_"
            for char in resource_id
        ).strip("._") or resource_type

        if self.project_manager.is_loaded:
            root = self.project_manager.project_root
        else:
            root = self.base_path

        collection = schema.get("collection", "")
        return root / collection / f"{safe_id}.json"

    def setup_generic_editor(self, workspace_widget, schema):
        """ワークスペース内に一覧（テーブル）と編集（フォーム）の2つのエディタをセットアップする"""
        editor_stack = workspace_widget.findChild(QStackedWidget, "editorStack")
        sub_tab_bar = workspace_widget.findChild(QTabBar, "subTabBar")
        if not editor_stack or not sub_tab_bar:
            return
            
        # 1. テーブルエディタ（一覧）の追加
        table_editor = self._load_ui(self.editor_path / "generic_table_editor.ui")
        if table_editor:
            editor_stack.addWidget(table_editor)
            sub_tab_bar.addTab("一覧")
            
            # モデルのセットアップ
            model = ResourceTableModel(schema, self.project_manager)
            table_view = table_editor.findChild(QTableView, "tableView")
            if table_view:
                table_view.setModel(model)
                table_view.horizontalHeader().setStretchLastSection(True)
                table_view.setSelectionBehavior(QTableView.SelectRows)
                table_view.setSelectionMode(QTableView.SingleSelection)
                table_view.doubleClicked.connect(lambda index: self._on_table_row_selected(workspace_widget, index))
            
            self.table_models[workspace_widget] = model
            model.load_data()
            
            # テーブル操作の接続
            search_edit = table_editor.findChild(QLineEdit, "tableSearchEdit")
            if search_edit:
                search_edit.textChanged.connect(model.filter)
                
            add_btn = table_editor.findChild(QPushButton, "tableAddRowButton")
            if add_btn:
                add_btn.clicked.connect(lambda: self.create_new_event()) # 暫定的に共通処理を使用
                
            del_btn = table_editor.findChild(QPushButton, "tableDeleteRowButton")
            if del_btn:
                del_btn.clicked.connect(lambda: self._delete_selected_table_row(workspace_widget))

        # 2. フォームエディタ（編集）の追加
        form_editor = self._load_ui(self.editor_path / "generic_form_editor.ui")
        if form_editor:
            editor_stack.addWidget(form_editor)
            sub_tab_bar.addTab("編集")
            
            # FormBuilderのセットアップ
            form_layout = form_editor.findChild(QVBoxLayout, "formLayout")
            builder = FormBuilder(form_layout, self.project_manager, self.schemas)
            builder.build(schema)
            self.builders[workspace_widget] = builder
            
            # 保存ボタン
            save_btn = form_editor.findChild(QWidget, "saveButton")
            if save_btn:
                save_btn.clicked.connect(lambda: self.save_workspace_data(workspace_widget, schema))

        # タブ切り替えの接続
        sub_tab_bar.currentChanged.connect(lambda idx: editor_stack.setCurrentIndex(idx + 1)) # +1 は emptyPage 分
        
        # 初期状態は一覧
        sub_tab_bar.setCurrentIndex(0)
        editor_stack.setCurrentIndex(1)

    def _on_table_row_selected(self, workspace_widget, index):
        """テーブルの行が選択（ダブルクリック）された際の処理"""
        model = self.table_models.get(workspace_widget)
        if not model: return
        
        path = model.get_path(index.row())
        if path:
            self.load_resource_into_form(workspace_widget, path)
            
            # 編集タブに切り替え
            sub_tab_bar = workspace_widget.findChild(QTabBar, "subTabBar")
            if sub_tab_bar:
                sub_tab_bar.setCurrentIndex(1)

    def _delete_selected_table_row(self, workspace_widget):
        """テーブルで選択されている行のリソースを削除"""
        table_view = workspace_widget.findChild(QTableView, "tableView")
        model = self.table_models.get(workspace_widget)
        if not table_view or not model: return
        
        selection = table_view.selectionModel().selectedRows()
        if not selection: return
        
        path = model.get_path(selection[0].row())
        if path:
            self.delete_resource_file(path)
            model.load_data() # リスト更新

    def load_resource_into_form(self, workspace_widget, path):
        """指定したパスのリソースを、ワークスペース内のフォームにロードする"""
        res_type, data = self.project_manager.load_resource(path)
        builder = self.builders.get(workspace_widget)
        if builder and data:
            builder.set_data(data)
            self.active_files[workspace_widget] = path
            workspace_widget.setProperty("resource_type", res_type)

    def save_workspace_data(self, workspace_widget, schema):
        """現在のフォームデータを保存する"""
        builder = self.builders.get(workspace_widget)
        if builder:
            data_file = self.base_path / "data" / f"{schema['resource_type']}_test.json"
            builder.save_to_json(data_file)
            print(f"データを保存しました: {data_file}")

    def _connect_once(self, owner, signal_name, callback):
        callback_self = getattr(callback, "__self__", None)
        callback_func = getattr(callback, "__func__", callback)
        key = (id(owner), signal_name, id(callback_self), callback_func)
        if key in self._connected_slots:
            return

        getattr(owner, signal_name).connect(callback)
        self._connected_slots.add(key)

    def setup_actions(self):
        """メニューとボタンのアクションを接続"""
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QToolBar

        # ツールバー設定
        toolbar = self.main_window.findChild(QToolBar, "mainToolBar")
        if toolbar:
            toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
            toolbar.setIconSize(QSize(28, 28))
        
        # アクションへのアイコン適用と接続
        action_map = {
            "actionNewProject": ("new-file-flat.svg", self.new_project),
            "actionOpenProject": ("folder-open.svg", self.open_project),
            "actionSaveProject": ("save.svg", self.save_current_file),
            "actionExport": ("export.svg", self.run_export),
            "actionValidate": ("lightbulb-filament-48.svg", self.run_validation),
        }
        
        for act_name, (icon_file, callback) in action_map.items():
            act = self.main_window.findChild(QAction, act_name)
            if act:
                icon_path = self.icons_path / icon_file
                if icon_path.exists():
                    act.setIcon(QIcon(str(icon_path)))
                self._connect_once(act, "triggered", callback)

        # クイックボタンへのアイコン適用と接続
        button_map = {
            "quickSaveButton": ("save.svg", self.save_current_file),
            "quickExportButton": ("export.svg", self.run_export),
            "quickValidateButton": ("lightbulb-filament-48.svg", self.run_validation),
        }
        
        for btn_name, (icon_file, callback) in button_map.items():
            btn = self.main_window.findChild(QPushButton, btn_name)
            if btn:
                icon_path = self.icons_path / icon_file
                if icon_path.exists():
                    btn.setIcon(QIcon(str(icon_path)))
                
                self._connect_once(btn, "clicked", callback)

        # 「表示」メニューにドックの切り替えアクションを追加
        menu_view = self.main_window.findChild(QMenu, "menuView")
        if menu_view:
            for dock in self.docks:
                menu_view.addAction(dock.toggleViewAction())

    def setup_project_tree(self):
        """プロジェクトツリーのセットアップ"""
        self.project_tree_view = self.main_window.findChild(QTreeView, "projectTreeView")
        if not self.project_tree_view:
            return
            
        self.file_model = QFileSystemModel()
        self.file_model.setReadOnly(False)
        self.project_tree_view.setModel(self.file_model)
        
        # 不要な列を隠す
        for i in range(1, 4):
            self.project_tree_view.hideColumn(i)
            
        self.project_tree_view.doubleClicked.connect(self._on_tree_item_double_clicked)
        self.project_tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_tree_view.customContextMenuRequested.connect(self._show_tree_context_menu)


    def new_project(self):
        """新規プロジェクトの作成"""
        dir_path = QFileDialog.getExistingDirectory(self.main_window, "新規プロジェクトのディレクトリを選択")
        if not dir_path:
            return
            
        if self.project_manager.create_new(dir_path):
            self.update_project_ui()
            QMessageBox.information(self.main_window, "完了", f"プロジェクトを作成しました:\n{dir_path}")

    def open_project(self):
        """既存プロジェクトの読み込み"""
        dir_path = QFileDialog.getExistingDirectory(self.main_window, "プロジェクトディレクトリを選択")
        if not dir_path:
            return
            
        if self.project_manager.load(dir_path):
            self.update_project_ui()
        else:
            QMessageBox.warning(self.main_window, "エラー", "有効なプロジェクトが見つかりません。")

    def update_project_ui(self):
        """プロジェクトの状態をUIに反映"""
        root_path = self.project_manager.project_root
        self.file_model.setRootPath(str(root_path))
        self.project_tree_view.setRootIndex(self.file_model.index(str(root_path)))
        
        proj_label = self.main_window.findChild(QWidget, "projectNameLabel")
        if proj_label:
            proj_label.setText(f"プロジェクト: {self.project_manager.project_data.get('name')}")

    def setup_logs(self):
        """ログパネルのセットアップ"""
        log_table = self.main_window.findChild(QTableView, "logTableView")
        if log_table:
            log_table.setModel(self.log_model)
            log_table.horizontalHeader().setStretchLastSection(True)
            
        clear_btn = self.main_window.findChild(QWidget, "logClearButton")
        if clear_btn:
            clear_btn.clicked.connect(self.log_model.clear)

    def run_validation(self):
        """プロジェクト全体の検査を実行"""
        if not self.project_manager.is_loaded:
            QMessageBox.warning(self.main_window, "エラー", "プロジェクトが開かれていません。")
            return
            
        self.main_window.statusBar().showMessage("検査を実行中...")
        issues = self.validator.validate_project()
        
        self.log_model.clear()
        for issue in issues:
            self.log_model.add_item(issue.to_dict())
            
        self.main_window.statusBar().showMessage(f"検査完了: {len(issues)} 件 of 指摘事項があります", 5000)

    def setup_dependency_workspace(self, workspace):
        """依存関係ワークスペースのセットアップ"""
        graph_view = workspace.findChild(QGraphicsView, "dependencyGraphView")
        if graph_view:
            graph_view.setScene(self.graph_scene)
            graph_view.setRenderHint(QPainter.Antialiasing)
            
        refresh_btn = workspace.findChild(QPushButton, "dependencyRefreshButton")
        if refresh_btn:
            refresh_btn.clicked.connect(self.run_dependency_analysis)

    def run_dependency_analysis(self):
        """依存関係の解析とグラフ更新"""
        if not self.project_manager.is_loaded:
            return
            
        self.main_window.statusBar().showMessage("依存関係を解析中...")
        graph = self.dependency_analyzer.analyze()
        self.graph_scene.build_graph(graph)
        self.main_window.statusBar().showMessage(f"解析完了: {len(graph.all_nodes)} ノード", 3000)

    def setup_asset_workspace(self, workspace):
        """アセットワークスペースのセットアップ"""
        sub_tab_bar = workspace.findChild(QTabBar, "assetSubTabBar")
        asset_stack = workspace.findChild(QStackedWidget, "assetStack")
        if not sub_tab_bar or not asset_stack:
            return
            
        # 既存のタブをクリア
        while sub_tab_bar.count() > 0: sub_tab_bar.removeTab(0)
            
        sub_tab_bar.addTab("画像一覧")
        sub_tab_bar.addTab("画像編集")
        
        # 1. 画像一覧ページ
        list_page = QWidget()
        list_layout = QHBoxLayout(list_page)
        
        self.asset_list_model = QStandardItemModel()
        self.asset_list_view = QListView()
        self.asset_list_view.setModel(self.asset_list_model)
        self.asset_list_view.setViewMode(QListView.IconMode)
        self.asset_list_view.setIconSize(QSize(100, 100))
        self.asset_list_view.setResizeMode(QListView.Adjust)
        self.asset_list_view.setWrapping(True)
        self.asset_list_view.clicked.connect(self._on_asset_selected)
        list_layout.addWidget(self.asset_list_view, 1)
        
        self.asset_preview_label = QLabel("プレビュー")
        self.asset_preview_label.setMinimumSize(120, 120)
        self.asset_preview_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.asset_preview_label.setAlignment(Qt.AlignCenter)
        self.asset_preview_label.setStyleSheet("border: 1px solid gray;")
        self.asset_preview_label.setScaledContents(True)
        list_layout.addWidget(self.asset_preview_label)
        
        asset_stack.addWidget(list_page)
        
        # 2. 画像編集ページ
        editor_page = self._load_ui(self.editor_path / "generic_image_editor.ui")
        if editor_page:
            asset_stack.addWidget(editor_page)
            
        sub_tab_bar.currentChanged.connect(lambda idx: asset_stack.setCurrentIndex(idx + 1))
        sub_tab_bar.setCurrentIndex(0)
        asset_stack.setCurrentIndex(1)
        
        # インポートボタン
        import_btn = workspace.findChild(QPushButton, "assetImportButton")
        if import_btn:
            import_btn.clicked.connect(self.import_asset_dialog)
            
        self.refresh_asset_list()

    def refresh_asset_list(self):
        """アセットリストを更新"""
        if not self.project_manager.is_loaded: return
        self.asset_list_model.clear()
        
        assets = self.project_manager.get_assets()
        for asset_path in assets:
            item = QStandardItem(asset_path.name)
            item.setData(str(asset_path), Qt.UserRole) # 相対パスを保持
            
            # 簡易サムネイル (画像のみ)
            full_path = self.project_manager.project_root / asset_path
            if full_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".bmp"]:
                pixmap = QPixmap(str(full_path))
                if not pixmap.isNull():
                    item.setIcon(pixmap.scaled(100, 100, Qt.KeepAspectRatio))
            
            self.asset_list_model.appendRow(item)

    def _on_asset_selected(self, index):
        """アセット選択時のプレビュー表示"""
        rel_path = index.data(Qt.UserRole)
        if not rel_path: return
        
        full_path = self.project_manager.project_root / rel_path
        if full_path.exists() and full_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".bmp"]:
            pixmap = QPixmap(str(full_path))
            self.asset_preview_label.setPixmap(pixmap.scaled(self.asset_preview_label.size(), Qt.KeepAspectRatio))
        else:
            self.asset_preview_label.setText("プレビュー不可")

    def import_asset_dialog(self):
        """外部ファイルをインポート"""
        file_path, _ = QFileDialog.getOpenFileName(self.main_window, "アセットを読み込む")
        if file_path:
            rel_path = self.project_manager.import_asset(file_path)
            if rel_path:
                self.main_window.statusBar().showMessage(f"インポートしました: {rel_path}", 3000)
        self.refresh_asset_list()

    def setup_proposal_queue(self, dock):
        """提案キューのセットアップ"""
        list_view = dock.findChild(QListView, "proposalListView")
        if list_view:
            list_view.setModel(self.proposal_model)
            
        accept_btn = dock.findChild(QPushButton, "proposalAcceptButton")
        if accept_btn:
            accept_btn.clicked.connect(self.accept_selected_proposal)
            
        # ダミー提案を追加
        self.add_dummy_proposal()

    def add_dummy_proposal(self):
        """テスト用のダミー提案を追加"""
        dummy = ProposalItem(
            "テスト提案: 新しいイベント",
            "フランスが降伏した際のイベントを追加します。",
            "simple_event",
            {"id": "test.fra.1", "name": "フランス降伏", "desc": "フランスは平和を求めた。"}
        )
        self.proposal_model.add_proposal(dummy)

    def accept_selected_proposal(self):
        """選択された提案をプロジェクトに反映"""
        if self.proposal_model.rowCount() == 0: return
        
        proposal = self.proposal_model.proposals[0]
        proposal.status = "採用済み"
        
        # ファイル名の決定
        if self.project_manager.project_root:
            target_path = self.project_manager.project_root / "data" / "events" / f"{proposal.data['id']}.json"
            self.project_manager.save_resource(target_path, proposal.res_type, proposal.data)
            
            self.main_window.statusBar().showMessage(f"提案を採用しました: {proposal.title}", 3000)
            self.proposal_model.layoutChanged.emit()

    def setup_ai_assistant(self, dock):
        """AIアシスタントドックのセットアップ"""
        container = dock.findChild(QWidget, "aiActionContainer")
        if not container: return
        layout = container.layout()
        
        actions = [
            ("説明文を生成", self.ai_generate_description),
            ("名称案を生成", self.ai_generate_names),
            ("翻訳 (日->英)", self.ai_translate_ja_en),
            ("エラーの解説", self.ai_explain_errors),
        ]
        
        for label, callback in actions:
            btn = QPushButton(label)
            btn.clicked.connect(callback)
            layout.addWidget(btn)
        
        layout.addStretch()

    def ai_generate_description(self):
        """現在のリソースの説明文をAIで生成"""
        self.main_window.statusBar().showMessage("AIが説明文を生成中...", 3000)
        
        proposal = ProposalItem(
            "AI提案: 説明文の改善",
            "現在の設定に基づいて、より没入感のある説明文を提案します。",
            "simple_event",
            {"desc": "AIによって生成された、歴史的な背景を考慮した魅力的なイベント説明文です。"}
        )
        self.proposal_model.add_proposal(proposal)

    def ai_generate_names(self):
        """名称案をAIで生成"""
        proposal = ProposalItem(
            "AI提案: 名称のバリエーション",
            "国家やイベントにふさわしい名前をいくつか提案します。",
            "simple_event",
            {"name": "生成されたかっこいい名前"}
        )
        self.proposal_model.add_proposal(proposal)

    def ai_translate_ja_en(self):
        """選択中のテキストを翻訳"""
        self.main_window.statusBar().showMessage("AIが翻訳中...", 3000)

    def ai_explain_errors(self):
        """ログにあるエラーの解決策をAIが解説"""
        self.main_window.statusBar().showMessage("AIがエラーを分析中...", 3000)

    def setup_localisation_workspace(self, workspace):
        """ローカライズワークスペースのセットアップ"""
        table_view = workspace.findChild(QTableView, "localisationTableView")
        if table_view:
            table_view.setModel(self.loc_model)
            table_view.horizontalHeader().setStretchLastSection(True)
            
        lang_combo = workspace.findChild(QComboBox, "languageCombo")
        if lang_combo:
            lang_combo.addItems(self.loc_manager.languages)
            lang_combo.currentTextChanged.connect(self._on_loc_lang_changed)
            
        translate_btn = workspace.findChild(QPushButton, "localisationAutoTranslateButton")
        if translate_btn:
            translate_btn.clicked.connect(self.run_ai_translation)
            
        # ダミーデータの追加
        if not self.loc_manager.loc_data:
            self.loc_manager.set_value("EVT_NAME_001", "japanese", "フランス降伏")
            self.loc_manager.set_value("EVT_DESC_001", "japanese", "フランスは力尽き、休戦を申し入れた。")
            self.loc_model.update_data()

    def _on_loc_lang_changed(self, lang):
        self.loc_model.current_lang = lang
        self.loc_model.update_data()

    def run_ai_translation(self):
        """AI翻訳を実行"""
        if not self.project_manager.is_loaded: return
        self.main_window.statusBar().showMessage("AI翻訳を実行中...", 5000)
        
        # 簡易的な一括翻訳モック
        for key in self.loc_model.keys:
            ja_val = self.loc_manager.get_value(key, "japanese")
            if ja_val and not self.loc_manager.get_value(key, self.loc_model.current_lang):
                # 翻訳結果（モック）
                self.loc_manager.set_value(key, self.loc_model.current_lang, f"[AI] Translated: {ja_val}")
        
        self.loc_model.update_data()
        self.main_window.statusBar().showMessage("AI翻訳が完了しました", 3000)

    def run_export(self):
        """プロジェクトのエクスポートを実行"""
        if not self.project_manager.is_loaded:
            QMessageBox.warning(self.main_window, "エラー", "プロジェクトが開かれていません。")
            return
            
        output_dir = self.project_manager.project_root / "generated"
        self.main_window.statusBar().showMessage(f"エクスポート中: {output_dir} ...")
        
        try:
            if self.exporter.export_all(output_dir):
                QMessageBox.information(self.main_window, "完了", f"エクスポートが完了しました:\n{output_dir}")
                self.main_window.statusBar().showMessage("エクスポート完了", 5000)
        except Exception as e:
            QMessageBox.critical(self.main_window, "エラー", f"エクスポートに失敗しました:\n{e}")
            self.main_window.statusBar().showMessage("エクスポート失敗", 5000)

    def _on_tree_item_double_clicked(self, index):
        """ツリー項目ダブルクリック時の処理 (ファイルを開く)"""
        path = Path(self.file_model.filePath(index))
        if path.is_file() and path.suffix == ".json":
            self.open_resource_file(path)

    def _show_tree_context_menu(self, position):
        """プロジェクトツリーの右クリックメニュー表示"""
        index = self.project_tree_view.indexAt(position)
        menu = QMenu()
        
        # 共通アクション
        new_event_act = menu.addAction("新規イベント作成")
        menu.addSeparator()
        
        if index.isValid():
            path = Path(self.file_model.filePath(index))
            if path.is_file():
                open_act = menu.addAction("開く")
                dup_act = menu.addAction("複製")
                del_act = menu.addAction("削除")
                
                action = menu.exec(self.project_tree_view.viewport().mapToGlobal(position))
                
                if action == open_act:
                    self.open_resource_file(path)
                elif action == dup_act:
                    self.duplicate_resource_file(path)
                elif action == del_act:
                    self.delete_resource_file(path)
            else:
                # ディレクトリの場合
                action = menu.exec(self.project_tree_view.viewport().mapToGlobal(position))
        else:
            action = menu.exec(self.project_tree_view.viewport().mapToGlobal(position))

        if action == new_event_act:
            self.create_new_event()

    def create_new_event(self):
        """新しいイベントファイルを作成"""
        if not self.project_manager.is_loaded:
            QMessageBox.warning(self.main_window, "エラー", "プロジェクトが開かれていません。")
            return
            
        event_dir = self.project_manager.project_root / "data" / "events"
        event_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイル名の決定
        i = 1
        while True:
            file_name = f"event_{i:03d}.json"
            file_path = event_dir / file_name
            if not file_path.exists():
                break
            i += 1
            
        # 初期データ
        initial_data = {
            "id": f"new_event_{i}",
            "name": "新規イベント",
            "desc": ""
        }
        self.project_manager.save_resource(file_path, "simple_event", initial_data)
        self.open_resource_file(file_path)
        
        # テーブルモデルの更新
        for model in self.table_models.values():
            if model.schema.get('resource_type') == "simple_event":
                model.load_data()

    def open_resource_file(self, path):
        """リソースファイルを読み込んでエディタに表示"""
        res_type, data = self.project_manager.load_resource(path)
        if not res_type:
            return
            
        schema = self.schemas.get(res_type)
        if not schema:
            QMessageBox.warning(self.main_window, "エラー", f"不明なリソースタイプです: {res_type}")
            return
            
        # 既存のタブがあれば切り替え、なければ新規作成
        # TODO: 既に開いているかどうかの判定を改善
        label = path.name
        self.add_workspace(label, "generic_workspace.ui", schema)
        
        new_widget = self.central_stack.widget(self.central_stack.count() - 1)
        new_widget.setProperty("resource_type", res_type) # リソースタイプを保持
        builder = self.builders.get(new_widget)
        if builder:
            builder.set_data(data)
            self.active_files[new_widget] = path
            
        self.main_tab_bar.setCurrentIndex(self.main_tab_bar.count() - 1)

    def save_current_file(self):
        """現在アクティブなタブの内容を保存"""
        index = self.main_tab_bar.currentIndex()
        if index < 0: return
        
        # index + 1 は centralStack のインデックス (1つ目は空ページ)
        current_widget = self.central_stack.widget(index + 1)
        builder = self.builders.get(current_widget)
        file_path = self.active_files.get(current_widget)
        
        if builder and file_path:
            res_type = current_widget.property("resource_type") or "simple_event"
            data = builder.get_data()
            self.project_manager.save_resource(file_path, res_type, data)
            print(f"保存完了: {file_path}")
            self.main_window.statusBar().showMessage(f"保存しました: {file_path.name}", 3000)
            
            # テーブルモデルの更新
            model = self.table_models.get(current_widget) # 実際には workspace_widget
            if not model:
                # 親の親が workspace_widget かもしれないので検索
                for w, m in self.table_models.items():
                    if w.isAncestorOf(current_widget):
                        m.load_data()
            elif model:
                model.load_data()

    def duplicate_resource_file(self, path):
        """ファイルを複製"""
        new_path = path.parent / f"{path.stem}_copy{path.suffix}"
        # 重複回避
        i = 1
        while new_path.exists():
            new_path = path.parent / f"{path.stem}_copy_{i}{path.suffix}"
            i += 1
            
        shutil.copy2(path, new_path)
        print(f"複製完了: {new_path}")

    def delete_resource_file(self, path):
        """ファイルを削除"""
        ret = QMessageBox.question(
            self.main_window, "確認", 
            f"本当に削除しますか？\n{path.name}",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            path.unlink()
            print(f"削除完了: {path}")
            # テーブルモデルの更新
            for model in self.table_models.values():
                model.load_data()

    def _on_workspace_tab_changed(self, index):
        """タブ切り替え時の表示更新"""
        self.central_stack.setCurrentIndex(index + 1)

    def run(self):
        return self.app.exec()

if __name__ == "__main__":
    app = ModStudioApp()
    sys.exit(app.run())
