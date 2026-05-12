import os
import json
from PySide6.QtWidgets import QFileDialog, QListWidgetItem
from PySide6.QtCore import Qt

# デフォルト設定
DEFAULT_SETTINGS = {
    "game_path": "",
    "output_languages": ["l_english", "l_japanese"]
}

def setup(widget, plugin, project_path):
    """
    プラグイン設定画面の初期化ロジック。
    widget: settings.ui をロードしたウィジェット
    plugin: 現在の Plugin オブジェクト
    project_path: 現在のプロジェクト（MOD）のルートパス
    """
    
    # settings.json はプラグインのフォルダ内に保存する（共通設定）
    settings_file = os.path.join(plugin.path, "settings.json")
    
    # 設定の読み込み、または初期化
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except:
            settings = DEFAULT_SETTINGS.copy()
    else:
        settings = DEFAULT_SETTINGS.copy()
        # ファイルがない場合は出力する
        save_settings(settings_file, settings)

    # 1. ゲーム本体のパス設定
    game_path_edit = widget.findChild(object, "gamePathEdit")
    browse_button = widget.findChild(object, "gamePathBrowseButton")
    
    if game_path_edit:
        game_path_edit.setText(settings.get("game_path", ""))
        game_path_edit.textChanged.connect(lambda text: (
            settings.update({"game_path": text}),
            save_settings(settings_file, settings)
        ))
    
    if browse_button:
        def on_browse():
            path = QFileDialog.getExistingDirectory(widget, "Hearts of Iron IV 本体の場所を選択", game_path_edit.text())
            if path:
                game_path_edit.setText(path)
        browse_button.clicked.connect(on_browse)
        
    # 2. ローカリゼーション言語リスト
    lang_list = widget.findChild(object, "outputLanguagesList")
    if lang_list:
        lang_list.clear()
        
        available_langs = []
        for element in plugin.elements:
            if element.id == "localisation":
                available_langs = element.raw.get("languages", [])
                break
        
        selected_langs = settings.get("output_languages", [])
        
        lang_list.blockSignals(True)
        for lang in available_langs:
            lang_id = lang.get("id")
            lang_name = lang.get("name", lang_id)
            
            item = QListWidgetItem(lang_name)
            item.setData(Qt.ItemDataRole.UserRole, lang_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            
            check_state = Qt.CheckState.Checked if lang_id in selected_langs else Qt.CheckState.Unchecked
            item.setCheckState(check_state)
            lang_list.addItem(item)
        lang_list.blockSignals(False)
            
        def on_item_changed(item):
            current_selected = settings.get("output_languages", [])
            lang_id = item.data(Qt.ItemDataRole.UserRole)
            
            if item.checkState() == Qt.CheckState.Checked:
                if lang_id not in current_selected:
                    current_selected.append(lang_id)
            else:
                if lang_id in current_selected:
                    current_selected.remove(lang_id)
            
            settings["output_languages"] = current_selected
            save_settings(settings_file, settings)

        lang_list.itemChanged.connect(on_item_changed)

def save_settings(path, settings):
    """設定をJSONファイルに保存する"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save settings to {path}: {e}")
