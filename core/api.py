import os
from core.i18n import tr
from core.utils import load_svg_icon as _load_svg_icon

_current_project_path = None
_project_path_handlers = []
_loc_changed_handlers = []

_message_handler = None
_progress_handler = None
_open_tab_handler = None
_open_untitled_tab_handler = None
_active_tab_handler = None
_tab_plugin_handler = None
_editor_ready_handler = None
_active_plugin = None
BUILTIN_TEXT_EDITOR_ID = "core.plain_text"

def set_project_path(path: str):
    global _current_project_path
    _current_project_path = path
    for handler in _project_path_handlers:
        try:
            handler(path)
        except Exception as e:
            print(f"Error in project path handler: {e}")

def get_project_path() -> str:
    return _current_project_path

def load_svg_icon(path: str, color_hex: str):
    return _load_svg_icon(path, color_hex)

def register_project_path_handler(handler):
    global _project_path_handlers
    _project_path_handlers.append(handler)

# --- ローカライズ更新通知 API ---
def register_loc_changed_handler(handler):
    global _loc_changed_handlers
    _loc_changed_handlers.append(handler)

def notify_loc_changed():
    for handler in _loc_changed_handlers:
        try:
            handler()
        except Exception as e:
            print(f"Error in loc changed handler: {e}")

_file_saved_handlers = []

def register_file_saved_handler(handler):
    global _file_saved_handlers
    _file_saved_handlers.append(handler)

def notify_file_saved(file_path: str):
    for handler in _file_saved_handlers:
        try:
            handler(file_path)
        except Exception as e:
            print(f"Error in file saved handler: {e}")


# --- メッセージ API ---
def show_message(text: str, timeout: int = 3000):
    if _message_handler:
        _message_handler(text, timeout)
    else:
        print(f"[StatusBar] {text}")

# --- 進捗 API ---
def set_progress(value: int, text: str = ""):
    """value: 0-100, text: 表示するラベル"""
    if _progress_handler:
        _progress_handler(value, text)

# --- タブ API ---
def open_tab(file_path: str, editor_id: str = None, params: dict = None):
    """指定したファイルをタブで開く（既に開いていれば切り替える）"""
    if _open_tab_handler:
        _open_tab_handler(file_path, editor_id, params)

def open_untitled_tab(name: str, content: str = "", editor_id: str = BUILTIN_TEXT_EDITOR_ID):
    """メモリ上でのみ存在する新規タブを開く（保存時にファイル名指定）"""
    if _open_untitled_tab_handler:
        _open_untitled_tab_handler(name, content, editor_id)

def get_active_tab():
    """現在アクティブなタブ情報を返す。タブがなければ None。"""
    if _active_tab_handler:
        return _active_tab_handler()
    return None

def get_tab_plugin(widget=None):
    """指定タブ、または現在アクティブなタブに属するプラグインを返す。"""
    if _tab_plugin_handler:
        return _tab_plugin_handler(widget)
    return None

# --- エディタ準備完了通知 API ---
def notify_editor_ready(widget):
    """エディタウィジェットが自身の初期化（パース等）が完了したことを通知する"""
    if _editor_ready_handler:
        _editor_ready_handler(widget)

def get_active_plugin():
    return _active_plugin

# --- 診断プロバイダ (Linter) API ---
_diagnostics_providers = {}  # { extension: provider_func }

def register_diagnostics_provider(extension: str, provider_func):
    """
    プラグインがファイル拡張子（例: '.txt'）に対応する診断関数を登録する。
    provider_func: (file_path: str, content: str) -> list[Diagnostic] を返す関数。
    """
    global _diagnostics_providers
    _diagnostics_providers[extension.lower()] = provider_func

def get_diagnostics(file_path: str, content: str) -> list:
    """
    指定されたファイルの診断結果（Diagnostic のリスト）を取得する。
    """
    _, ext = os.path.splitext(file_path)
    provider = _diagnostics_providers.get(ext.lower())
    if provider:
        try:
            return provider(file_path, content)
        except Exception as e:
            print(f"Error in diagnostics provider for {ext}: {e}")
    return []


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


def _call_plugin_hook(plugin, hook_name: str, payload: dict = None, default=None):
    """Call an optional plugin hook."""
    if not plugin or not getattr(plugin, "module", None) or not hook_name:
        return default

    payload = payload or {}
    module = plugin.module
    candidates = [
        f"hook_{hook_name.replace('.', '_')}",
        hook_name.replace(".", "_"),
    ]
    for name in candidates:
        func = getattr(module, name, None)
        if callable(func):
            try:
                result = _call_named_plugin_hook_func(func, plugin, payload)
                return default if result is None else result
            except Exception as e:
                print(f"Error in plugin hook {plugin.id}.{hook_name}: {e}")
                return default

    for name in ("on_plugin_hook", "handle_plugin_hook", "on_hook"):
        func = getattr(module, name, None)
        if callable(func):
            try:
                result = _call_generic_plugin_hook_func(func, plugin, hook_name, payload)
                return default if result is None else result
            except Exception as e:
                print(f"Error in plugin hook {plugin.id}.{hook_name}: {e}")
                return default

    return default


def plugin_translate(
    plugin,
    key: str,
    fallback: str = None,
    language: str = None,
    context: str = None,
    metadata: dict = None,
) -> str:
    """Ask a plugin to translate a key through the optional i18n hook."""
    fallback_text = fallback if fallback is not None else key
    if not key:
        return fallback_text or ""

    result = _call_plugin_hook(
        plugin,
        "i18n.translate",
        {
            "key": key,
            "fallback": fallback_text,
            "language": language,
            "context": context,
            "metadata": metadata or {},
        },
        default=None,
    )

    if isinstance(result, dict):
        text = result.get("text")
        return text if text is not None else fallback_text
    if isinstance(result, str) and result:
        return result
    return fallback_text
