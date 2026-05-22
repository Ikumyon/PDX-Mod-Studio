import os
from core.i18n import tr

_current_project_path = None
_event_hooks = {}

_message_handler = None
_progress_handler = None
_open_tab_handler = None
_open_untitled_tab_handler = None
_active_tab_handler = None
_tab_plugin_id_handler = None
_editor_ready_handler = None
_active_plugin_id_handler = None
_plugin_object_resolver = None
BUILTIN_TEXT_EDITOR_ID = "core.plain_text"

def set_project_path(path: str):
    global _current_project_path
    _current_project_path = path
    emit_event("project_path_changed", path)

def get_project_path() -> str:
    return _current_project_path

def subscribe_event(event_name: str, handler):
    handlers = _event_hooks.setdefault(str(event_name), [])
    handlers.append(handler)


def emit_event(event_name: str, *args, **kwargs):
    for handler in list(_event_hooks.get(str(event_name), [])):
        try:
            handler(*args, **kwargs)
        except Exception as e:
            print(f"Error in event hook {event_name}: {e}")


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

def get_tab_plugin_id(tab_id=None):
    """指定タブ、または現在アクティブなタブに属するプラグインIDを返す。"""
    if _tab_plugin_id_handler:
        return _tab_plugin_id_handler(tab_id)
    return None

# --- エディタ準備完了通知 API ---
def notify_editor_ready(tab_id):
    """エディタが自身の初期化完了を tab_id で通知する。"""
    if _editor_ready_handler:
        _editor_ready_handler(tab_id)

def get_active_plugin_id():
    """現在アクティブなプラグインIDを返す。"""
    if _active_plugin_id_handler:
        return _active_plugin_id_handler()
    return None

def _resolve_plugin_object(plugin_id):
    if _plugin_object_resolver:
        return _plugin_object_resolver(plugin_id)
    return None

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


def _call_plugin_hook(plugin, hook_name: str, payload: dict = None, default=None):
    """Call an optional plugin hook."""
    if not plugin or not hook_name:
        return default
    return plugin.call_named_hook(hook_name, payload=payload, default=default)


def plugin_translate(
    plugin_id,
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
    plugin = _resolve_plugin_object(plugin_id)

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
