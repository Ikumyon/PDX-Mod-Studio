import os
import json
from PySide6.QtCore import QFile, Qt
from PySide6.QtUiTools import QUiLoader
from core.i18n import tr
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
    QDialogButtonBox,
    QGroupBox,
    QPushButton
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
            "default_excludes": ".git, __pycache__, .vs",
            "editor_auto_close_brackets": True,
            "editor_auto_close_pairs": "{}()[]\"\"''",
            "color_keyword": "#569cd6",
            "color_string": "#ce9178",
            "color_number": "#b5cea8",
            "color_comment": "#6a9955"
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

        # 自動補完UI
        self.groupAutoClose = self.findChild(QGroupBox, "groupAutoClose")
        self.listAutoClosePairs = self.findChild(QListWidget, "listAutoClosePairs")
        self.lineOpenChar = self.findChild(QLineEdit, "lineOpenChar")
        self.lineCloseChar = self.findChild(QLineEdit, "lineCloseChar")
        self.btnPrefAddPair = self.findChild(QPushButton, "btnPrefAddPair")
        self.btnPrefRemovePair = self.findChild(QPushButton, "btnPrefRemovePair")

        # 色設定UI
        self.btnColorKeyword = self.findChild(QPushButton, "btnColorKeyword")
        self.btnColorString = self.findChild(QPushButton, "btnColorString")
        self.btnColorNumber = self.findChild(QPushButton, "btnColorNumber")
        self.btnColorComment = self.findChild(QPushButton, "btnColorComment")

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

        # 自動補完設定の追加・削除アクション
        if self.btnPrefAddPair:
            self.btnPrefAddPair.clicked.connect(self._add_pair_from_input)
        if self.btnPrefRemovePair:
            self.btnPrefRemovePair.clicked.connect(self._remove_selected_pair)

        # 色設定ボタンのアクション
        if self.btnColorKeyword:
            self.btnColorKeyword.clicked.connect(lambda: self._select_color(self.btnColorKeyword))
        if self.btnColorString:
            self.btnColorString.clicked.connect(lambda: self._select_color(self.btnColorString))
        if self.btnColorNumber:
            self.btnColorNumber.clicked.connect(lambda: self._select_color(self.btnColorNumber))
        if self.btnColorComment:
            self.btnColorComment.clicked.connect(lambda: self._select_color(self.btnColorComment))

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

        # 自動補完設定のロード
        if self.groupAutoClose:
            self.groupAutoClose.setChecked(bool(settings_manager.get("editor_auto_close_brackets", True)))
        
        if self.listAutoClosePairs:
            self.listAutoClosePairs.clear()
            pairs_str = settings_manager.get("editor_auto_close_pairs", "{}()[]\"\"''")
            for i in range(0, len(pairs_str) - 1, 2):
                open_char = pairs_str[i]
                close_char = pairs_str[i+1]
                self.listAutoClosePairs.addItem(f"{open_char}  {close_char}")

        # 色設定のロード
        if self.btnColorKeyword:
            self._init_color_button(self.btnColorKeyword, settings_manager.get("color_keyword", "#569cd6"))
        if self.btnColorString:
            self._init_color_button(self.btnColorString, settings_manager.get("color_string", "#ce9178"))
        if self.btnColorNumber:
            self._init_color_button(self.btnColorNumber, settings_manager.get("color_number", "#b5cea8"))
        if self.btnColorComment:
            self._init_color_button(self.btnColorComment, settings_manager.get("color_comment", "#6a9955"))

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

        if self.groupAutoClose:
            settings_manager.set("editor_auto_close_brackets", self.groupAutoClose.isChecked())

        if self.listAutoClosePairs:
            pairs_list = []
            for i in range(self.listAutoClosePairs.count()):
                item_text = self.listAutoClosePairs.item(i).text()
                if len(item_text) >= 4:
                    pairs_list.append(item_text[0] + item_text[3])
            settings_manager.set("editor_auto_close_pairs", "".join(pairs_list))

        # 色設定のセーブ
        if self.btnColorKeyword:
            settings_manager.set("color_keyword", self.btnColorKeyword.property("color_val"))
        if self.btnColorString:
            settings_manager.set("color_string", self.btnColorString.property("color_val"))
        if self.btnColorNumber:
            settings_manager.set("color_number", self.btnColorNumber.property("color_val"))
        if self.btnColorComment:
            settings_manager.set("color_comment", self.btnColorComment.property("color_val"))

        settings_manager.set("ignore_gitignore", self.cbIgnoreGitignore.isChecked())
        settings_manager.set("ignore_ignore", self.cbIgnoreIgnore.isChecked())
        settings_manager.set("ignore_files_exclude", self.cbIgnoreFilesExclude.isChecked())
        settings_manager.set("ignore_search_exclude", self.cbIgnoreSearchExclude.isChecked())
        settings_manager.set("default_excludes", self.lineDefaultExcludes.text())

        settings_manager.save()
        settings_manager.apply_fonts(self.parent())
        self.accept()

    def _add_pair_from_input(self):
        if not self.lineOpenChar or not self.lineCloseChar or not self.listAutoClosePairs:
            return
        open_char = self.lineOpenChar.text()
        close_char = self.lineCloseChar.text()
        if len(open_char) != 1 or len(close_char) != 1:
            return
        
        # 重複チェック
        new_item_text = f"{open_char}  {close_char}"
        for i in range(self.listAutoClosePairs.count()):
            if self.listAutoClosePairs.item(i).text() == new_item_text:
                return  # すでに登録済み
                
        self.listAutoClosePairs.addItem(new_item_text)
        self.lineOpenChar.clear()
        self.lineCloseChar.clear()

    def _remove_selected_pair(self):
        if not self.listAutoClosePairs:
            return
        selected_items = self.listAutoClosePairs.selectedItems()
        for item in selected_items:
            self.listAutoClosePairs.takeItem(self.listAutoClosePairs.row(item))

    def _init_color_button(self, button, hex_color):
        from PySide6.QtGui import QColor
        color = QColor(hex_color)
        button.setProperty("color_val", hex_color)
        # 背景色を適用し、明るさ(lightness)に応じて文字色を黒か白に自動調整
        text_color = "#000000" if color.lightness() > 128 else "#ffffff"
        button.setStyleSheet(f"background-color: {hex_color}; color: {text_color}; border: 1px solid #7a7a7a; border-radius: 4px; padding: 4px;")
        button.setText(hex_color)

    def _select_color(self, button):
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        current_color = QColor(button.property("color_val") or "#ffffff")
        color = QColorDialog.getColor(current_color, self, tr("カラー設定", "Settings"))
        if color.isValid():
            self._init_color_button(button, color.name())
