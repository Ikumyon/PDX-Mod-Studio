import os

_current_project_path = None
_project_path_handlers = []
_loc_changed_handlers = []
_mode_changed_handlers = []
_message_handler = None
_progress_handler = None
_tabs_handler = None
_mode_handler = None
_active_plugin_handler = None

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

def register_mode_changed_handler(handler):
    global _mode_changed_handlers
    _mode_changed_handlers.append(handler)

def notify_mode_changed(file_path: str, mode_id: str):
    for handler in _mode_changed_handlers:
        try:
            handler(file_path, mode_id)
        except Exception as e:
            print(f"Error in mode changed handler: {e}")

# --- メッセージ API ---
def register_message_handler(handler):
    global _message_handler
    _message_handler = handler

def show_message(text: str, timeout: int = 3000):
    if _message_handler:
        _message_handler(text, timeout)
    else:
        print(f"[StatusBar] {text}")

# --- 進捗 API ---
def register_progress_handler(handler):
    global _progress_handler
    _progress_handler = handler

def set_progress(value: int, text: str = ""):
    """value: 0-100, text: 表示するラベル"""
    if _progress_handler:
        _progress_handler(value, text)

# --- タブ API ---
def register_tabs_handler(handler_dict):
    global _tabs_handler
    _tabs_handler = handler_dict

def get_open_tabs() -> list:
    """開いているタブの情報をリストで返す"""
    if _tabs_handler and "get_tabs" in _tabs_handler:
        return _tabs_handler["get_tabs"]()
    return []

def open_tab(file_path: str):
    """指定したファイルをタブで開く（既に開いていれば切り替える）"""
    if _tabs_handler and "open_tab" in _tabs_handler:
        _tabs_handler["open_tab"](file_path)

def register_mode_handler(handler_dict):
    global _mode_handler
    _mode_handler = handler_dict

def get_element_for_file(file_path: str):
    if _mode_handler and "get_element_for_file" in _mode_handler:
        return _mode_handler["get_element_for_file"](file_path)
    return None

def get_modes_for_file(file_path: str, include_script: bool = True):
    if _mode_handler and "get_modes_for_file" in _mode_handler:
        return _mode_handler["get_modes_for_file"](file_path, include_script)
    return [{"id": "script_mode", "name": "スクリプトモード"}] if include_script else []

def get_current_mode(file_path: str = None):
    if _mode_handler and "get_current_mode" in _mode_handler:
        return _mode_handler["get_current_mode"](file_path)
    return None

def switch_mode(mode_id: str, file_path: str = None) -> bool:
    if _mode_handler and "switch_mode" in _mode_handler:
        return bool(_mode_handler["switch_mode"](mode_id, file_path))
    return False

def refresh_modes(file_path: str = None) -> int:
    if _mode_handler and "refresh_modes" in _mode_handler:
        return int(_mode_handler["refresh_modes"](file_path) or 0)
    return 0

def register_active_plugin_handler(handler):
    global _active_plugin_handler
    _active_plugin_handler = handler

def get_active_plugin():
    if _active_plugin_handler:
        return _active_plugin_handler()
    return None
