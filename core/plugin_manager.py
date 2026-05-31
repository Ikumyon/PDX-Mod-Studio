import os
import json
import importlib.util
from decimal import Decimal
import tomllib
import core.api
from core.syntax_engine import (
    GrammarAssetLoader,
    resolve_manifest_display_text,
    translate_from_files_map,
)

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
        self.description = self.raw.get("description", "")
        self.elements = [] # ModElementのリスト
        self.module = None # ロードされたPythonモジュール
        self.entry_point = self.raw.get("entry_point")
        self.entry_kind = self._detect_entry_kind(self.entry_point, self.raw.get("entry_kind"))
        self._assistant_widget_factory = None

    def clear_elements(self):
        self.elements.clear()

    def add_element(self, id, name, path, element_dir=None, raw=None):
        element = ModElement(
            id=id,
            name=name,
            path=path,
            plugin=self,
            element_dir=element_dir,
            raw=raw,
        )
        self.elements.append(element)
        return element

    def get_element_attribute(self, element, attribute, default=None, **kwargs):
        """プラグインロジックから属性を取得する。コア側はデフォルト値を持たない。"""
        method_name = f"get_{attribute}"
        if self.module and hasattr(self.module, method_name):
            func = getattr(self.module, method_name)
            return func(element, **kwargs)
        return default

    def _detect_entry_kind(self, entry_point, explicit_kind=None):
        if explicit_kind:
            return str(explicit_kind).lower()
        if not entry_point:
            return "none"
        _, ext = os.path.splitext(str(entry_point))
        ext = ext.lower()
        if ext == ".py":
            return "python"
        if ext == ".exe":
            return "executable"
        if ext in (".dll", ".pyd", ".so", ".dylib"):
            return "native"
        if ext == ".c":
            return "source"
        return ext.lstrip(".") or "unknown"

    def set_assistant_widget_factory(self, factory):
        self._assistant_widget_factory = factory

    def create_assistant_widget(self, parent):
        if callable(self._assistant_widget_factory):
            return self._assistant_widget_factory(parent)
        return None

    def resolve_path(self, relative_path):
        if not relative_path:
            return self.path
        normalized = str(relative_path).replace("/", os.sep)
        return os.path.normpath(os.path.join(self.path, normalized))

    def read_text_asset(self, relative_path, encoding="utf-8"):
        with open(self.resolve_path(relative_path), "r", encoding=encoding) as handle:
            return handle.read()

    def read_json_asset(self, relative_path, encoding="utf-8"):
        with open(self.resolve_path(relative_path), "r", encoding=encoding) as handle:
            return json.load(handle)

    def read_toml_asset(self, relative_path):
        with open(self.resolve_path(relative_path), "rb") as handle:
            return tomllib.load(handle, parse_float=Decimal)

    def get_manifest_file_map(self):
        grammar_data = self.raw.get("grammar")
        grammar_modes_path = None
        if isinstance(grammar_data, dict):
            grammar_modes_path = grammar_data.get("grammar_modes_path")
        if grammar_modes_path:
            with open(grammar_modes_path, "rb") as handle:
                return tomllib.load(handle, parse_float=Decimal)

        grammar_modes = self.raw.get("grammar_modes")
        if not isinstance(grammar_modes, str) or not grammar_modes:
            raise ValueError(f"Plugin '{self.id}' is missing the required 'grammar_modes' manifest entry.")
        return self.read_toml_asset(grammar_modes)

    def load_elements_from_files(self):
        self.clear_elements()
        grammar_data = self.raw.get("grammar")
        if not grammar_data or not isinstance(grammar_data, dict):
            return

        modes = grammar_data.get("modes")
        if not isinstance(modes, list):
            return

        for mode in modes:
            if not isinstance(mode, dict):
                continue
            mode_id = mode.get("id")
            name_key = mode.get("name_key")
            path_pattern = mode.get("path")

            if not mode_id or not name_key:
                continue

            # 翻訳キーから翻訳表示名を解決
            resolved_name = self.translate(name_key)

            self.add_element(
                id=mode_id,
                name=resolved_name,
                path=path_pattern,
                element_dir=None,
                raw=mode,
            )

    def translate(self, key, fallback=None, context=None, metadata=None):
        if self.module:
            return core.api.plugin_translate(
                self.id,
                key,
                fallback=fallback,
                context=context,
                metadata=metadata or {},
            )
        return translate_from_files_map(
            plugin_root=self.path,
            manifest=self.raw,
            key=key,
            fallback=fallback,
            language=None,
        )

    def initialize(self):
        func = getattr(self.module, "initialize", None) if self.module else None
        if callable(func):
            func(self)

    def show_settings(self, parent, project_path):
        """プラグインの設定画面を表示する"""
        func = getattr(self.module, "show_settings", None) if self.module else None
        if callable(func):
            func(self, parent, project_path)
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(parent, "プラグイン設定", f"プラグイン '{self.name}' には設定項目がありません。")

    def export_project_data(self, context):
        func = getattr(self.module, "export_project_data", None) if self.module else None
        if callable(func):
            return func(self, context) or {}
        return {}

    def import_project_data(self, context, data):
        func = getattr(self.module, "import_project_data", None) if self.module else None
        if callable(func):
            func(self, context, data or {})

    def call_named_hook(self, hook_name, payload=None, default=None):
        if not self.module or not hook_name:
            return default
        payload = payload or {}
        candidates = [
            f"hook_{hook_name.replace('.', '_')}",
            hook_name.replace(".", "_"),
        ]
        for name in candidates:
            func = getattr(self.module, name, None)
            if not callable(func):
                continue
            try:
                result = _call_named_plugin_hook_func(func, self, payload)
                return default if result is None else result
            except Exception as error:
                print(f"Error in plugin hook {self.id}.{hook_name}: {error}")
                return default

        for name in ("on_plugin_hook", "handle_plugin_hook", "on_hook"):
            func = getattr(self.module, name, None)
            if not callable(func):
                continue
            try:
                result = _call_generic_plugin_hook_func(func, self, hook_name, payload)
                return default if result is None else result
            except Exception as error:
                print(f"Error in plugin hook {self.id}.{hook_name}: {error}")
                return default

        return default

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
                plugin_root = os.path.join(os.path.dirname(self.plugins_dir), manifest["path"])
                resolved_name = resolve_manifest_display_text(
                    manifest,
                    "name_key",
                    "name",
                    default=p_id,
                    plugin_id=p_id,
                    translate=lambda key, fallback: translate_from_files_map(
                        plugin_root=plugin_root,
                        manifest=manifest,
                        key=key,
                        fallback=fallback,
                        language=None,
                    ),
                )
                resolved_description = resolve_manifest_display_text(
                    manifest,
                    "desc_key",
                    "description",
                    default="",
                    plugin_id=p_id,
                    translate=lambda key, fallback: translate_from_files_map(
                        plugin_root=plugin_root,
                        manifest=manifest,
                        key=key,
                        fallback=fallback,
                        language=None,
                    ),
                )
                plugin = Plugin(
                    id=p_id,
                    name=resolved_name,
                    version=manifest.get("version", "1.0.0"),
                    path=plugin_root,
                    icon_path=os.path.join(plugin_root, manifest.get("icon", "")) if manifest.get("icon") else None,
                    raw={
                        **manifest,
                        "name": resolved_name,
                        "description": resolved_description,
                    }
                )
                
                # 1. 静的文法アセットローダーの起動
                grammar_loader = GrammarAssetLoader()
                grammar_result = grammar_loader.load_grammar_manifest(plugin_root, manifest)
                if grammar_result:
                    plugin.raw["grammar"] = grammar_result
                    print(f"Grammar plugin '{p_id}' verified.")

                # 2. 動的プログラムフックローダーの起動
                entry_point = manifest.get("entry_point")
                if entry_point:
                    self._load_plugin_logic(plugin, entry_point)

                plugin.load_elements_from_files()
                
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
            if plugin.entry_kind != "python":
                print(f"Plugin {plugin.id}: unsupported entry kind '{plugin.entry_kind}' for current loader")
                return
            module_name = f"plugin_logic_{plugin.id}"
            module = load_module_from_path(module_name, logic_path)
            plugin.module = module
            plugin.initialize()
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


def _call_named_plugin_hook_func(func, plugin, payload: dict):
    try:
        return func(plugin, payload)
    except TypeError:
        return func(payload)


def _call_generic_plugin_hook_func(func, plugin, hook_name: str, payload: dict):
    try:
        return func(plugin, hook_name, payload)
    except TypeError:
        try:
            return func(hook_name, payload)
        except TypeError:
            return func(payload)
