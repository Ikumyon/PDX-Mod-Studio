import os
import json
from PySide6.QtWidgets import QFileDialog, QListWidgetItem, QDialog, QVBoxLayout, QMessageBox, QLineEdit, QComboBox, QPushButton, QLabel, QToolButton, QHBoxLayout, QScrollArea, QSplitter, QCheckBox
from PySide6.QtCore import Qt, QFile, QFileSystemWatcher, QTimer, QSize
from PySide6.QtGui import QIcon
from PySide6.QtUiTools import QUiLoader
from core.plugin_manager import ModElement
from plugins.hoi4.localisation.registry import LocalisationRegistry
import core.api

# グローバルなレジストリインスタンス
_registry = None
_watcher = None

# --- 設定関連の定数とロジック ---
DEFAULT_SETTINGS = {
    "game_path": "",
    "event_namespace": "{file}",
    "event_id_format": "{namespace}.{number}",
    "event_loc_file_format": "{lang}/{namespace}_l_{lang}.yml",
    "event_title_key_format": "{id}.t",
    "event_desc_key_format": "{id}.d",
    "event_option_key_format": "{id}.{a-z}",
    "decision_category_id_format": "{category}_{number}",
    "decision_id_format": "{category}_{number}",
    "decision_loc_file_format": "{lang}/decisions_l_{lang}.yml",
    "display_language": "l_japanese",
    "save_empty_localisation": False,
    "explicit_no_export": False
}

# 設定キーごとの利用可能な変数定義
VARIABLE_DEFINITIONS = {
    "event_namespace": ["{project_name}", "{file}"],
    "event_id_format": ["{namespace}", "{number}", "{file}", "{a-z}"],
    "event_loc_file_format": ["{id}", "{namespace}", "{lang}", "{file}"],
    "event_title_key_format": ["{id}", "{namespace}", "{number}", "{file}"],
    "event_desc_key_format": ["{id}", "{namespace}", "{number}", "{file}"],
    "event_option_key_format": ["{id}", "{a-z}", "{number}", "{namespace}", "{file}"],
    "decision_category_id_format": ["{file}", "{number}", "{a-z}"],
    "decision_id_format": ["{category}", "{number}", "{file}", "{a-z}"],
    "decision_loc_file_format": ["{id}", "{category}", "{lang}", "{file}"]
}

class VariableSelectorDialog(QDialog):
    """フォーマット変数を選択して編集するためのダイアログ"""
    def __init__(self, parent, variables, current_text):
        super().__init__(parent)
        self.setWindowTitle("変数を選択")
        
        layout = QVBoxLayout(self)
        
        # 変数ボタンの配置
        layout.addWidget(QLabel("利用可能な変数:"))
        btn_layout = QHBoxLayout()
        for var in variables:
            btn = QPushButton(var)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _, v=var: self.insert_variable(v))
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        layout.addSpacing(10)
        
        # プレビュー兼編集エリア
        layout.addWidget(QLabel("現在の形式:"))
        self.edit = QLineEdit(current_text)
        layout.addWidget(self.edit)
        
        # 決定ボタン
        self.ok_btn = QPushButton("決定")
        self.ok_btn.clicked.connect(self.accept)
        layout.addWidget(self.ok_btn)

    def insert_variable(self, var):
        self.edit.insert(var)
        self.edit.setFocus()

    def get_text(self):
        return self.edit.text()

def save_plugin_settings(path, settings):
    """設定をJSONファイルに保存する"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save settings to {path}: {e}")

def load_plugin_elements(plugin):
    """Load HoI4 element definitions from each element config.json."""
    plugin.elements.clear()
    for item in os.listdir(plugin.path):
        element_dir = os.path.join(plugin.path, item)
        if not os.path.isdir(element_dir):
            continue

        config_path = os.path.join(element_dir, "config.json")
        if not os.path.exists(config_path):
            continue

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            element = ModElement(
                id=item,
                name=config.get("name", item),
                path=config.get("path", ""),
                plugin=plugin,
                element_dir=element_dir,
                raw=config,
            )
            plugin.elements.append(element)
        except Exception as e:
            print(f"Failed to load HoI4 element {item}: {e}")

def get_colored_icon(path, color):
    """SVGの色を置換してQIconを生成する"""
    if not os.path.exists(path):
        return QIcon()
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            svg_data = f.read()
        
        # currentColor または #000000 を指定色（16進数）で置換
        hex_color = color.name()
        svg_data = svg_data.replace('currentColor', hex_color)
        svg_data = svg_data.replace('#000000', hex_color)
        
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap()
        pixmap.loadFromData(svg_data.encode('utf-8'), "SVG")
        return QIcon(pixmap)
    except Exception as e:
        print(f"Failed to colorize icon {path}: {e}")
        return QIcon(path)

def setup_settings_controls(widget, plugin, project_path):
    """設定画面の初期化ロジック"""
    settings_file = os.path.join(plugin.path, "settings.json")
    
    # 現在のテキストカラーを取得
    palette = widget.palette()
    text_color = palette.color(widget.foregroundRole())

    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except:
            settings = DEFAULT_SETTINGS.copy()
    else:
        settings = DEFAULT_SETTINGS.copy()
    
    # 不足しているデフォルト設定を補完
    updated = False
    for k, v in DEFAULT_SETTINGS.items():
        if k not in settings:
            settings[k] = v
            updated = True
    
    if updated or not os.path.exists(settings_file):
        save_plugin_settings(settings_file, settings)

    # 共通の変数選択ダイアログ表示用ヘルパー
    def open_variable_dialog(target_edit, settings_key):
        variables = VARIABLE_DEFINITIONS.get(settings_key, [])
        dialog = VariableSelectorDialog(widget, variables, target_edit.text())
        if dialog.exec() == QDialog.Accepted:
            target_edit.setText(dialog.get_text())

    # ゲーム本体のパス設定
    game_path_edit = widget.findChild(QLineEdit, "gamePathEdit")
    browse_button = widget.findChild(object, "gamePathBrowseButton")
    
    if game_path_edit:
        game_path_edit.setText(settings.get("game_path", ""))
        game_path_edit.textChanged.connect(lambda text: (
            settings.update({"game_path": text}),
            save_plugin_settings(settings_file, settings),
            getattr(plugin, "refresh_localisation", lambda: None)()
        ))
    
    if browse_button:
        def on_browse():
            path = QFileDialog.getExistingDirectory(widget, "Hearts of Iron IV 本体の場所を選択", game_path_edit.text())
            if path:
                game_path_edit.setText(path)
        browse_button.clicked.connect(on_browse)

    # 設定項目とウィジェット名のマッピング
    settings_map = {
        "eventNamespaceEdit": "event_namespace",
        "idFormatEdit": "event_id_format",
        "locFileFormatEdit": "event_loc_file_format",
        "titleKeyFormatEdit": "event_title_key_format",
        "descKeyFormatEdit": "event_desc_key_format",
        "optionKeyFormatEdit": "event_option_key_format",
        "decisionCategoryIdFormatEdit": "decision_category_id_format",
        "decisionIdFormatEdit": "decision_id_format",
        "decisionLocFileFormatEdit": "decision_loc_file_format"
    }

    # 各入力欄とBrowseボタン（鉛筆アイコン）の自動紐付け
    for widget_name, settings_key in settings_map.items():
        edit = widget.findChild(QLineEdit, widget_name)
        if not edit:
            continue
            
        # 既存の値セットと変更検知
        edit.setText(settings.get(settings_key, DEFAULT_SETTINGS[settings_key]))
        edit.textChanged.connect(lambda text, key=settings_key: (
            settings.update({key: text}),
            save_plugin_settings(settings_file, settings)
        ))
        
        # Browseボタンの自動検出とセットアップ
        # 命名規則: Edit -> BrowseButton (例: idFormatEdit -> idFormatBrowseButton)
        browse_name = widget_name.replace("Edit", "BrowseButton")
        browse_btn = widget.findChild(QToolButton, browse_name)
        
        if browse_btn:
            # 鉛筆アイコンの設定（テーマカラー適用）
            icon_path = os.path.join(plugin.path, "asset", "icons", "pencil.svg")
            browse_btn.setIcon(get_colored_icon(icon_path, text_color))
            browse_btn.setIconSize(QSize(16, 16))
            browse_btn.setText("")
            
            # クリックイベントの接続
            browse_btn.clicked.connect(lambda _, e=edit, k=settings_key: open_variable_dialog(e, k))

    # 表示優先言語のコンボボックス
    display_lang_combo = widget.findChild(QComboBox, "displayLanguageCombo")
    if display_lang_combo:
        display_lang_combo.clear()
        available_langs = []
        for element in plugin.elements:
            if element.id == "localisation":
                available_langs = element.raw.get("languages", [])
                break
        
        for lang in available_langs:
            lang_id = lang.get("id")
            lang_name = lang.get("name", lang_id)
            display_lang_combo.addItem(lang_name, lang_id)
        
        # 現在の値をセット
        current_display = settings.get("display_language", "l_japanese")
        idx = display_lang_combo.findData(current_display)
        if idx >= 0:
            display_lang_combo.setCurrentIndex(idx)
        
        display_lang_combo.currentIndexChanged.connect(lambda index: (
            settings.update({"display_language": display_lang_combo.itemData(index)}),
            save_plugin_settings(settings_file, settings),
            getattr(plugin, "refresh_localisation", lambda: None)()
        ))

    # 空の翻訳を保存するかどうかのチェックボックス
    save_empty_check = widget.findChild(QCheckBox, "saveEmptyLocCheck")
    if save_empty_check:
        save_empty_check.setChecked(settings.get("save_empty_localisation", False))
        save_empty_check.toggled.connect(lambda checked: (
            settings.update({"save_empty_localisation": checked}),
            save_plugin_settings(settings_file, settings)
        ))

    # チェック解除時に no を書き込むかどうかのチェックボックス
    explicit_no_check = widget.findChild(QCheckBox, "explicitNoCheck")
    if explicit_no_check:
        explicit_no_check.setChecked(settings.get("explicit_no_export", False))
        explicit_no_check.toggled.connect(lambda checked: (
            settings.update({"explicit_no_export": checked}),
            save_plugin_settings(settings_file, settings)
        ))

def initialize(plugin):
    """
    HoI4プラグインの初期化。
    """
    print(f"Initializing HoI4 Plugin: {plugin.name}")
    load_plugin_elements(plugin)
    
    global _registry, _watcher
    _registry = LocalisationRegistry()
    _watcher = QFileSystemWatcher()
    
    # 監視状態の管理用
    _mod_file_snapshots = {} # { path: mtime }
    _scan_timer = QTimer()
    _scan_timer.setSingleShot(True)
    _scan_timer.setInterval(300) # 300ms まとめる

    def update_registry():
        project_path = core.api.get_project_path()
        if not project_path:
            return
            
        settings_file = os.path.join(plugin.path, "settings.json")
        settings = DEFAULT_SETTINGS.copy()
        if os.path.exists(settings_file):
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings.update(json.load(f))
            except: pass
            
        game_path = settings.get("game_path")
        lang = settings.get("display_language", "l_japanese")
        
        # 初回スキャン
        _registry.rebuild(game_path, project_path, lang)
        
        # 監視の設定とスナップショットの作成
        mod_loc_dir = os.path.join(project_path, "localisation")
        if os.path.exists(mod_loc_dir):
            _setup_watcher(mod_loc_dir)

    def _setup_watcher(dir_path):
        paths = _watcher.directories()
        if paths: _watcher.removePaths(paths)
        watch_dirs = []
        for root, _, _ in os.walk(dir_path):
            watch_dirs.append(root)
        if watch_dirs:
            _watcher.addPaths(watch_dirs)
        
        # ファイル個別の監視も追加（変更検知を確実にするため）
        old_files = _watcher.files()
        if old_files: _watcher.removePaths(old_files)
        _mod_file_snapshots.clear()
        
        current_files = []
        for root, _, files in os.walk(dir_path):
            for f in files:
                if f.endswith(".yml"):
                    p = os.path.join(root, f)
                    current_files.append(p)
                    _mod_file_snapshots[p] = os.path.getmtime(p)
        
        if current_files:
            _watcher.addPaths(current_files)
        print(f"Started monitoring {len(current_files)} files in {len(watch_dirs)} directories under {dir_path}")

    def on_monitor_event(path):
        """監視イベントを検知したらタイマーをスタート"""
        _scan_timer.start()

    def process_pending_changes():
        """実際にレジストリを差分更新する"""
        project_path = core.api.get_project_path()
        if not project_path: return
        mod_loc_dir = os.path.join(project_path, "localisation")
        changed = False
        
        current_files = {}
        for root, _, files in os.walk(mod_loc_dir):
            for f in files:
                if f.endswith(".yml"):
                    p = os.path.join(root, f)
                    current_files[p] = os.path.getmtime(p)
        
        # 1. 削除されたファイルを特定
        for p in list(_mod_file_snapshots.keys()):
            if p not in current_files:
                print(f"File deleted: {p}")
                _registry.remove_file_entries(p)
                _watcher.removePath(p)
                del _mod_file_snapshots[p]
                changed = True
        
        # 2. 追加・変更されたファイルを特定
        for p, mtime in current_files.items():
            if p not in _mod_file_snapshots:
                print(f"File added: {p}")
                _registry.update_file(p, "mod")
                _watcher.addPath(p)
                _mod_file_snapshots[p] = mtime
                changed = True
            elif mtime > _mod_file_snapshots[p]:
                print(f"File modified: {p}")
                _registry.update_file(p, "mod")
                _mod_file_snapshots[p] = mtime
                changed = True
        
        if changed:
            if os.path.exists(mod_loc_dir):
                _setup_watcher(mod_loc_dir)
            core.api.notify_loc_changed()

    _watcher.directoryChanged.connect(on_monitor_event)
    _watcher.fileChanged.connect(on_monitor_event)
    _scan_timer.timeout.connect(process_pending_changes)

    # プロジェクトパスが確定・変更されたら自動的にスキャンと監視を開始
    core.api.register_project_path_handler(lambda path: update_registry())
    
    # 手動再読込用
    plugin.refresh_localisation = update_registry

    # 既にプロジェクトが開かれている場合は即座に初期化
    if core.api.get_project_path():
        update_registry()

    plugin.localisation_registry = _registry

def get_extension(element):
    """要素の拡張子を返す"""
    return element.raw.get("extension", ".txt")

def get_encoding(element, file_path=None):
    """要素のエンコーディングを返す"""
    return element.raw.get("encoding", "utf-8")

def get_icon(element):
    """要素のアイコンパス（element_dirからの相対パス）を返す"""
    return element.raw.get("icon")

def is_folder(element):
    """要素がフォルダかどうかを返す"""
    return element.raw.get("is_folder", False)

def show_settings(plugin, parent, project_path):
    """プラグインの設定画面を表示する"""
    ui_file_path = os.path.join(plugin.path, "settings.ui")
    ui_file = QFile(ui_file_path)
    if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
        return

    loader = QUiLoader()
    container = loader.load(ui_file, parent)
    ui_file.close()

    if not container:
        return

    # ダイアログの作成
    dialog = QDialog(parent)
    dialog.setWindowTitle("Hearts of Iron IV プラグイン設定")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(container)

    # 統合したセットアップ関数を呼び出し
    setup_settings_controls(container, plugin, project_path)

    dialog.exec()
