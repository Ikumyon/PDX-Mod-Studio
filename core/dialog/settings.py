import os
import json
from PySide6.QtCore import QFile, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QListWidget,
    QStackedWidget,
    QComboBox,
    QFontComboBox,
    QSpinBox,
    QCheckBox,
    QLineEdit,
    QDialogButtonBox
)
from PySide6.QtGui import QFont

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
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        # 1. UIフォントの適用
        ui_family = self.get("ui_font_family", "")
        ui_size = int(self.get("ui_font_size", 9))
        
        app = QApplication.instance()
        if app:
            if ui_family:
                font = QFont(ui_family, ui_size)
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


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._loader_root = None
        self._load_ui()
        self._setup_connections()
        self._load_settings()

    def _load_ui(self):
        # settings_dialog.ui のパス取得
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ui_path = os.path.join(base_dir, "ui", "dialogs", "settings_dialog.ui")
        
        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise FileNotFoundError(f"Could not open UI file: {ui_path}")

        try:
            loader = QUiLoader()
            loaded = loader.load(ui_file, self)
        finally:
            ui_file.close()

        if loaded is None:
            raise RuntimeError(f"Could not load UI file: {ui_path}")

        self._loader_root = loaded
        self.setLayout(loaded.layout())

        # ウィジェットの取得
        self.listCategories = self.findChild(QListWidget, "listCategories")
        self.stackedWidget = self.findChild(QStackedWidget, "stackedWidget")
        
        # 全般ページ
        self.comboLanguage = self.findChild(QComboBox, "comboLanguage")
        self.fontComboUI = self.findChild(QFontComboBox, "fontComboUI")
        self.spinUISize = self.findChild(QSpinBox, "spinUISize")
        self.fontComboEditor = self.findChild(QFontComboBox, "fontComboEditor")
        self.spinEditorSize = self.findChild(QSpinBox, "spinEditorSize")

        # 検索除外ページ
        self.cbIgnoreGitignore = self.findChild(QCheckBox, "cbIgnoreGitignore")
        self.cbIgnoreIgnore = self.findChild(QCheckBox, "cbIgnoreIgnore")
        self.cbIgnoreFilesExclude = self.findChild(QCheckBox, "cbIgnoreFilesExclude")
        self.cbIgnoreSearchExclude = self.findChild(QCheckBox, "cbIgnoreSearchExclude")
        self.lineDefaultExcludes = self.findChild(QLineEdit, "lineDefaultExcludes")

        # ボタンボックス
        self.buttonBox = self.findChild(QDialogButtonBox, "buttonBox")

        loaded.hide()

    def _setup_connections(self):
        # カテゴリリスト選択時に対応するページへ切り替え
        if self.listCategories and self.stackedWidget:
            self.listCategories.currentRowChanged.connect(self.stackedWidget.setCurrentIndex)
            # 初期選択を設定
            self.listCategories.setCurrentRow(0)

        # ボタンボックスの OK / キャンセル のシグナル接続
        if self.buttonBox:
            self.buttonBox.accepted.connect(self._save_settings_and_accept)
            self.buttonBox.rejected.connect(self.reject)

    def _load_settings(self):
        # 設定のロードとUIへの反映
        settings_manager.load()

        # UIフォント
        ui_font_family = settings_manager.get("ui_font_family", "")
        if ui_font_family:
            self.fontComboUI.setCurrentFont(QFont(ui_font_family))
        self.spinUISize.setValue(int(settings_manager.get("ui_font_size", 9)))

        # エディタフォント
        editor_font_family = settings_manager.get("editor_font_family", "")
        if editor_font_family:
            self.fontComboEditor.setCurrentFont(QFont(editor_font_family))
        self.spinEditorSize.setValue(int(settings_manager.get("editor_font_size", 12)))

        # 除外設定
        self.cbIgnoreGitignore.setChecked(bool(settings_manager.get("ignore_gitignore", True)))
        self.cbIgnoreIgnore.setChecked(bool(settings_manager.get("ignore_ignore", True)))
        self.cbIgnoreFilesExclude.setChecked(bool(settings_manager.get("ignore_files_exclude", True)))
        self.cbIgnoreSearchExclude.setChecked(bool(settings_manager.get("ignore_search_exclude", True)))
        self.lineDefaultExcludes.setText(str(settings_manager.get("default_excludes", ".git, __pycache__, .vs")))

    def _save_settings_and_accept(self):
        # UIから値を取得して設定に保存
        settings_manager.set("ui_font_family", self.fontComboUI.currentFont().family())
        settings_manager.set("ui_font_size", self.spinUISize.value())
        settings_manager.set("editor_font_family", self.fontComboEditor.currentFont().family())
        settings_manager.set("editor_font_size", self.spinEditorSize.value())

        settings_manager.set("ignore_gitignore", self.cbIgnoreGitignore.isChecked())
        settings_manager.set("ignore_ignore", self.cbIgnoreIgnore.isChecked())
        settings_manager.set("ignore_files_exclude", self.cbIgnoreFilesExclude.isChecked())
        settings_manager.set("ignore_search_exclude", self.cbIgnoreSearchExclude.isChecked())
        settings_manager.set("default_excludes", self.lineDefaultExcludes.text())

        settings_manager.save()
        settings_manager.apply_fonts(self.parent())
        self.accept()
