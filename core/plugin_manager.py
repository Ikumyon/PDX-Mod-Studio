import os
import json
import importlib.util
from PySide6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile

class ModElement:
    def __init__(
        self,
        id,
        name,
        path,
        extension,
        is_folder=False,
        icon_path=None,
        template=None,
        document_type=None,
        path_globs=None,
        form=None,
        logic=None,
        parser=None,
        parser_entry=None,
        schema=None,
        element_dir=None,
        raw=None,
    ):
        self.id = id
        self.name = name
        self.path = path
        self.extension = extension
        self.is_folder = is_folder
        self.icon_path = icon_path
        self.template = template
        self.document_type = document_type
        self.path_globs = path_globs or []
        self.form = form
        self.logic = logic
        self.parser = parser
        self.parser_entry = parser_entry
        self.schema = schema
        self.element_dir = element_dir
        self.raw = raw or {}

    def __repr__(self):
        return f"<ModElement {self.name} ({self.path})>"

class Plugin:
    def __init__(self, id, name, version, path, icon_path=None, raw=None):
        self.id = id
        self.name = name
        self.version = version
        self.path = path
        self.icon_path = icon_path
        self.raw = raw or {}
        self.elements = [] # ModElementのリスト
        self.settings_ui = None
        self.settings_json = None
        self.settings_logic = None
        self.settings_defs = []

    def __repr__(self):
        return f"<Plugin {self.name} ({self.id})>"

    def show_settings(self, parent, project_path):
        """プラグインの設定画面を表示する"""
        if not self.settings_ui:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(parent, "情報", f"プラグイン '{self.name}' には設定項目がありません。")
            return

        dialog = PluginSettingsDialog(self, project_path, parent)
        dialog.exec()

class PluginSettingsDialog(QDialog):
    def __init__(self, plugin, project_path, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.project_path = project_path
        self.setWindowTitle(f"{plugin.name} の設定")
        self.resize(500, 400)
        
        layout = QVBoxLayout(self)
        
        # UIファイルのロード
        self.content_widget = None
        if self.plugin.settings_ui:
            loader = QUiLoader()
            ui_file = QFile(self.plugin.settings_ui)
            if ui_file.open(QFile.ReadOnly):
                self.content_widget = loader.load(ui_file, self)
                ui_file.close()
                if self.content_widget:
                    layout.addWidget(self.content_widget)
        
        # ボタンボックスの追加
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)
        
        # ロジックの適用
        if self.plugin.settings_logic and self.content_widget:
            try:
                module = load_module_from_path("plugin_settings", self.plugin.settings_logic)
                if hasattr(module, "setup"):
                    module.setup(self.content_widget, self.plugin, self.project_path)
            except Exception as e:
                print(f"Failed to setup plugin settings logic: {e}")

class PluginManager:
    def __init__(self, plugins_dir):
        self.plugins_dir = plugins_dir
        self.plugins = []

    def load_plugins(self):
        self.plugins = []
        if not os.path.exists(self.plugins_dir):
            return []

        for item in os.listdir(self.plugins_dir):
            item_path = os.path.join(self.plugins_dir, item)
            if os.path.isdir(item_path):
                # plugin.json または profile.json を探す（互換性のため）
                config_path = os.path.join(item_path, "plugin.json")
                if not os.path.exists(config_path):
                    config_path = os.path.join(item_path, "profile.json")
                
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            
                            icon_name = data.get("icon")
                            icon_path = os.path.join(item_path, icon_name) if icon_name else None
                            
                            plugin = Plugin(
                                id=data.get("id", item),
                                name=data.get("name", item),
                                version=data.get("version", "unknown"),
                                path=item_path,
                                icon_path=icon_path,
                                raw=data
                            )
                            
                            # 設定関連のロード
                            self._load_settings(plugin)
                            
                            # 要素（ModElements）のロード
                            self._load_elements(plugin)
                            
                            self.plugins.append(plugin)
                    except Exception as e:
                        print(f"Failed to load plugin from {config_path}: {e}")
        
        return self.plugins

    def _load_settings(self, plugin):
        """プラグインの設定定義（form, schema, logic）をロードする"""
        form_name = plugin.raw.get("settings_form")
        if form_name:
            ui_path = os.path.join(plugin.path, form_name)
            if os.path.exists(ui_path):
                plugin.settings_ui = ui_path

        schema_name = plugin.raw.get("settings_schema")
        if schema_name:
            json_path = os.path.join(plugin.path, schema_name)
            if os.path.exists(json_path):
                plugin.settings_json = json_path
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        plugin.settings_defs = json.load(f)
                except Exception as e:
                    print(f"Failed to load settings definition from {json_path}: {e}")

        logic_name = plugin.raw.get("settings_logic")
        if logic_name:
            logic_path = os.path.join(plugin.path, logic_name)
            if os.path.exists(logic_path):
                plugin.settings_logic = logic_path

    def _load_elements(self, plugin):
        """プラグインフォルダ内のサブフォルダを走査して要素をロードする"""
        for item in os.listdir(plugin.path):
            element_dir = os.path.join(plugin.path, item)
            if os.path.isdir(element_dir):
                element_config_path = os.path.join(element_dir, "config.json")
                if os.path.exists(element_config_path):
                    try:
                        with open(element_config_path, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                            icon_name = config.get("icon")
                            icon_path = os.path.join(element_dir, icon_name) if icon_name else None
                            
                            element = ModElement(
                                id=item,
                                name=config.get("name", item),
                                path=config.get("path", ""),
                                extension=config.get("extension", ".txt"),
                                is_folder=config.get("is_folder", False),
                                icon_path=icon_path,
                                template=config.get("template"),
                                document_type=config.get("document_type"),
                                path_globs=config.get("path_globs", []),
                                form=config.get("form"),
                                logic=config.get("logic"),
                                parser=config.get("parser"),
                                parser_entry=config.get("parser_entry"),
                                schema=config.get("schema"),
                                element_dir=element_dir,
                                raw=config,
                            )
                            plugin.elements.append(element)
                    except Exception as e:
                        print(f"Failed to load element from {element_config_path}: {e}")

    def get_plugins(self):
        return self.plugins

def load_module_from_path(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
