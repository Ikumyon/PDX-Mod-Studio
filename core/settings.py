import os
import json

class SettingsManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SettingsManager, cls).__new__(cls, *args, **kwargs)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.settings_path = os.path.join(self.base_dir, "settings.json")
        self.defaults = {
            "ui_font_family": "",
            "ui_font_size": 9,
            "editor_font_family": "",
            "editor_font_size": 12,
            "ignore_gitignore": True,
            "ignore_ignore": True,
            "ignore_files_exclude": True,
            "ignore_search_exclude": True,
            "default_excludes": ".git, __pycache__, .vs"
        }
        self.settings = {}
        self.load()

    def load(self):
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
            except Exception as e:
                print(f"Failed to load settings: {e}")
                self.settings = {}
        else:
            self.settings = {}

        # デフォルト値の補完
        for k, v in self.defaults.items():
            if k not in self.settings:
                self.settings[k] = v

    def save(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def get(self, key, default=None):
        return self.settings.get(key, default if default is not None else self.defaults.get(key))

    def set(self, key, value):
        self.settings[key] = value

    def apply_fonts(self, window=None):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
        
        # 1. UIフォントの適用
        ui_family = self.get("ui_font_family", "")
        ui_size = int(self.get("ui_font_size", 9))
        
        # QApplication.instance().setStyleSheet() を使ってアプリ全体のフォントを強制反映
        app = QApplication.instance()
        if app:
            css = f"QWidget {{ font-size: {ui_size}pt; }}"
            if ui_family:
                css = f"QWidget {{ font-family: '{ui_family}'; font-size: {ui_size}pt; }}"
            app.setStyleSheet(css)
            
            # 念のため QFont も設定
            if ui_family:
                font = QFont(ui_family, ui_size)
                app.setFont(font)
            else:
                font = app.font()
                font.setPointSize(ui_size)
                app.setFont(font)
            
        # 2. エディタフォントの適用（開いているエディタ全てに対して）
        if window and hasattr(window, "editorTabs") and window.editorTabs:
            editor_family = self.get("editor_font_family", "")
            editor_size = int(self.get("editor_font_size", 12))
            
            font_editor = QFont()
            if editor_family:
                font_editor.setFamily(editor_family)
            font_editor.setPointSize(editor_size)
            
            for i in range(window.editorTabs.count()):
                widget = window.editorTabs.widget(i)
                if widget:
                    widget.setFont(font_editor)

settings_manager = SettingsManager()
