import os
import json
from PySide6.QtWidgets import QFileDialog, QListWidgetItem, QDialog, QVBoxLayout, QMessageBox, QLineEdit, QComboBox, QPushButton
from PySide6.QtCore import Qt, QFile, QFileSystemWatcher, QTimer
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
    "event_id_format": "{namespace}.{number}",
    "event_loc_file_format": "{namespace}_{lang}.yml",
    "event_title_key_format": "{id}.t",
    "event_desc_key_format": "{id}.d",
    "event_option_key_format": "{id}.{a-z}",
    "display_language": "l_japanese"
}

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

def setup_settings_controls(widget, plugin, project_path):
    """設定画面の初期化ロジック"""
    settings_file = os.path.join(plugin.path, "settings.json")
    
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

    # イベントエディタ設定の同期
    settings_map = {
        "idFormatEdit": "event_id_format",
        "locFileFormatEdit": "event_loc_file_format",
        "titleKeyFormatEdit": "event_title_key_format",
        "descKeyFormatEdit": "event_desc_key_format",
        "optionKeyFormatEdit": "event_option_key_format"
    }

    for widget_name, settings_key in settings_map.items():
        edit = widget.findChild(QLineEdit, widget_name)
        if edit:
            edit.setText(settings.get(settings_key, DEFAULT_SETTINGS[settings_key]))
            edit.textChanged.connect(lambda text, key=settings_key: (
                settings.update({key: text}),
                save_plugin_settings(settings_file, settings)
            ))
        
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
    
def setup_settings_ui_legacy(widget, project_path, plugin):
    settings_file = os.path.join(plugin.path, "settings.json")
    
    def on_save_clicked():
        # GUIの各項目から現在の設定値を読み取る
        new_settings = {
            "game_path": widget.findChild(QLineEdit, "gamePathEdit").text(),
            "display_language": widget.findChild(QComboBox, "languageCombo").currentData(),
            # ... 他の設定項目
        }
        
        # ファイルに書き込む
        try:
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(new_settings, f, indent=4, ensure_ascii=False)
            
            # 再スキャンを強制
            plugin.refresh_localisation()
            core.api.show_message("設定を保存し、ローカライズ情報を再読込しました")
        except Exception as e:
            core.api.show_message(f"保存に失敗しました: {e}")

    # 保存ボタンの取得と接続 (UIファイル内のオブジェクト名に合わせる)
    save_btn = widget.findChild(QPushButton, "saveButton")
    if save_btn:
        save_btn.clicked.connect(on_save_clicked)
    
    # このプラグイン内の各要素フォルダを走査して登録する（実装詳細はプラグインに閉じる）
    plugin_path = plugin.path
    for item in os.listdir(plugin_path):
        element_dir = os.path.join(plugin_path, item)
        if os.path.isdir(element_dir):
            config_path = os.path.join(element_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        
                    # コアの ModElement を作成して登録
                    element = ModElement(
                        id=item,
                        name=config.get("name", item),
                        path=config.get("path", ""),
                        plugin=plugin,
                        element_dir=element_dir,
                        raw=config # JSONデータをそのまま持たせておく
                    )
                    plugin.elements.append(element)
                except Exception as e:
                    print(f"Failed to load HoI4 element {item}: {e}")

# --- 属性取得のフック関数 ---
# コア側 (Plugin.get_element_attribute) から呼び出される

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
