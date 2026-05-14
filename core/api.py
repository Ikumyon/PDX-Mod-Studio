import os

_current_project_path = None
_project_path_handlers = []
_loc_changed_handlers = []

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

def open_tab(file_path: str, editor_id: str = None):
    """指定したファイルをタブで開く（既に開いていれば切り替える）"""
    if _tabs_handler and "open_tab" in _tabs_handler:
        _tabs_handler["open_tab"](file_path, editor_id)


def register_editor_handler(handler_dict):
    global _mode_handler
    _mode_handler = handler_dict

def get_element_for_file(file_path: str):
    if _mode_handler and "get_element_for_file" in _mode_handler:
        return _mode_handler["get_element_for_file"](file_path)
    return None

def get_editors_for_file(file_path: str, include_script: bool = True):
    if _mode_handler and "get_editors_for_file" in _mode_handler:
        return _mode_handler["get_editors_for_file"](file_path, include_script)
    return [{"id": "text", "name": "テキストエディタ"}] if include_script else []


def register_active_plugin_handler(handler):
    global _active_plugin_handler
    _active_plugin_handler = handler

def get_active_plugin():
    if _active_plugin_handler:
        return _active_plugin_handler()
    return None
