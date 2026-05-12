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
        plugin,
        element_dir=None,
        raw=None,
    ):
        self.id = id
        self.name = name
        self.path = path
        self.plugin = plugin # 所属プラグインオブジェクト
        self.element_dir = element_dir
        self.raw = raw or {} # プラグイン内部で自由に使用するデータ

    def __getattr__(self, name):
        if name in self.raw:
            return self.raw[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

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
        self.module = None # ロードされたPythonモジュール

    def get_element_attribute(self, element, attribute, default=None, **kwargs):
        """プラグインロジックから属性を取得する。コア側はデフォルト値を持たない。"""
        method_name = f"get_{attribute}"
        if self.module and hasattr(self.module, method_name):
            func = getattr(self.module, method_name)
            return func(element, **kwargs)
        return default

    def show_settings(self, parent, project_path):
        """プラグインの設定画面を表示する"""
        if self.module and hasattr(self.module, "show_settings"):
            self.module.show_settings(self, parent, project_path)
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(parent, "プラグイン設定", f"プラグイン '{self.name}' には設定項目がありません。")

    def __repr__(self):
        return f"<Plugin {self.name} ({self.id})>"

class PluginManager:
    def __init__(self, plugins_dir):
        self.plugins_dir = plugins_dir
        self.plugins = []
        self.registry_path = os.path.join(os.path.dirname(self.plugins_dir), "plugins_registry.json")

    def load_plugins(self):
        """
        1. プラグインをディレクトリから自動検出し、最新のマニフェスト情報を取得する。
        2. レジストリから有効/無効設定を読み込む。
        3. 有効なプラグインをロードする。
        """
        # プラグインの自動検出
        discovered = self.discover_plugins()
        
        # レジストリ（ユーザー設定）の読み込み
        registry_settings = self._load_registry_settings()

        self.plugins = []
        
        for p_id, manifest in discovered.items():
            # レジストリ設定を確認（未登録ならデフォルトで有効）
            is_enabled = registry_settings.get(p_id, {}).get("enabled", True)
            
            if not is_enabled:
                continue

            try:
                # マニフェストの情報に基づき、Plugin オブジェクトを作成
                # path は discover_plugins で設定済み
                plugin = Plugin(
                    id=p_id,
                    name=manifest.get("name", p_id),
                    version=manifest.get("version", "1.0.0"),
                    path=os.path.join(os.path.dirname(self.plugins_dir), manifest["path"]),
                    icon_path=os.path.join(os.path.dirname(self.plugins_dir), manifest["path"], manifest.get("icon", "")) if manifest.get("icon") else None,
                    raw=manifest
                )
                
                # 指定されたエントリーポイント（.py）をロード
                entry_point = manifest.get("entry_point")
                if entry_point:
                    self._load_plugin_logic(plugin, entry_point)
                
                self.plugins.append(plugin)
                print(f"Successfully loaded plugin: {plugin.name} (via manifest)")
            except Exception as e:
                print(f"Failed to load plugin {p_id}: {e}")
        
        # 登録情報を整理して保存（無効化設定などを維持するため）
        self._save_registry_settings(discovered, registry_settings)
        
        return self.plugins

    def _load_plugin_logic(self, plugin, entry_point):
        """指定されたエントリーポイントをロードして初期化する"""
        logic_path = os.path.join(plugin.path, entry_point)
        if not os.path.exists(logic_path):
            print(f"Entry point not found: {logic_path}")
            return
            
        try:
            module_name = f"plugin_logic_{plugin.id}"
            module = load_module_from_path(module_name, logic_path)
            plugin.module = module
            
            if hasattr(module, "initialize"):
                module.initialize(plugin)
        except Exception as e:
            print(f"Failed to load plugin logic from {logic_path}: {e}")

    def discover_plugins(self):
        """pluginsディレクトリを走査して、plugin_manifest.jsonを持つフォルダを特定する"""
        discovered = {}
        if not os.path.exists(self.plugins_dir):
            return discovered
            
        for item in os.listdir(self.plugins_dir):
            plugin_path = os.path.join(self.plugins_dir, item)
            if os.path.isdir(plugin_path):
                manifest_path = os.path.join(plugin_path, "plugin_manifest.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, 'r', encoding='utf-8') as f:
                            manifest = json.load(f)
                            plugin_id = manifest.get("id")
                            if plugin_id:
                                # 相対パスを保存
                                manifest["path"] = os.path.join("plugins", item).replace("\\", "/")
                                discovered[plugin_id] = manifest
                    except Exception as e:
                        print(f"Failed to read manifest for {item}: {e}")
        return discovered

    def _load_registry_settings(self):
        """レジストリからユーザー設定（enabled等）を読み込む"""
        if not os.path.exists(self.registry_path):
            return {}
        try:
            with open(self.registry_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # { id: { settings } } の形式で返す
                return {p["id"]: p for p in data.get("plugins", [])}
        except Exception:
            return {}

    def _save_registry_settings(self, discovered, registry_settings):
        """現在のプラグイン構成と設定をレジストリに保存する"""
        new_registry_data = []
        for p_id in discovered:
            # 既存の設定があれば引き継ぐ
            enabled = registry_settings.get(p_id, {}).get("enabled", True)
            new_registry_data.append({
                "id": p_id,
                "enabled": enabled
            })
            
        try:
            with open(self.registry_path, 'w', encoding='utf-8') as f:
                json.dump({"plugins": new_registry_data}, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save registry: {e}")

    def get_plugins(self):
        return self.plugins

def load_module_from_path(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
