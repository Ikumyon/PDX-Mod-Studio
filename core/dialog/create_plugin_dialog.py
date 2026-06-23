import os
import re
import json
from PySide6.QtCore import QFile, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QDialog,
    QMessageBox,
    QLineEdit,
    QComboBox,
    QPlainTextEdit,
    QDialogButtonBox
)
from core.i18n import tr

class CreatePluginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.created_plugin_id = None
        self._load_ui()
        self._setup_connections()
        self._init_languages()

    def _load_ui(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ui_path = os.path.join(base_dir, "ui", "dialogs", "create_plugin_dialog.ui")

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

        self.setLayout(loaded.layout())

        # ウィジェットの取得
        self.lineId = self.findChild(QLineEdit, "lineId")
        self.comboDefaultLang = self.findChild(QComboBox, "comboDefaultLang")
        self.lineName = self.findChild(QLineEdit, "lineName")
        self.lineVersion = self.findChild(QLineEdit, "lineVersion")
        self.lineFolder = self.findChild(QLineEdit, "lineFolder")
        self.lineDeps = self.findChild(QLineEdit, "lineDeps")
        self.textDesc = self.findChild(QPlainTextEdit, "textDesc")
        self.buttonBox = self.findChild(QDialogButtonBox, "buttonBox")

        loaded.hide()

    def _setup_connections(self):
        if self.buttonBox:
            self.buttonBox.accepted.connect(self._on_accepted)
            self.buttonBox.rejected.connect(self.reject)

    def _init_languages(self):
        if not self.comboDefaultLang:
            return
        # 主要な言語コードの初期設定
        langs = ["ja", "en", "zh_CN", "de", "fr", "es", "ru"]
        self.comboDefaultLang.clear()
        self.comboDefaultLang.addItems(langs)
        self.comboDefaultLang.setCurrentText("ja")

    def _on_accepted(self):
        # 1. 入力の取得とトリミング
        plugin_id = self.lineId.text().strip() if self.lineId else ""
        plugin_name = self.lineName.text().strip() if self.lineName else ""
        default_lang = self.comboDefaultLang.currentText().strip() if self.comboDefaultLang else "ja"
        version = self.lineVersion.text().strip() if self.lineVersion else "1.0.0"
        folder_name = self.lineFolder.text().strip() if self.lineFolder else ""
        deps_text = self.lineDeps.text().strip() if self.lineDeps else ""
        description = self.textDesc.toPlainText().strip() if self.textDesc else ""

        # 2. バリデーション
        if not plugin_id:
            QMessageBox.warning(self, tr("入力エラー", "CreatePlugin"), tr("プラグインIDを入力してください。", "CreatePlugin"))
            return

        # IDは英数字とアンダースコアのみ
        if not re.match(r"^[a-zA-Z0-9_]+$", plugin_id):
            QMessageBox.warning(
                self,
                tr("入力エラー", "CreatePlugin"),
                tr("プラグインIDには半角英数字とアンダースコア(_)のみ使用できます。", "CreatePlugin")
            )
            return

        if not plugin_name:
            QMessageBox.warning(self, tr("入力エラー", "CreatePlugin"), tr("プラグイン名を入力してください。", "CreatePlugin"))
            return

        if not default_lang:
            QMessageBox.warning(self, tr("入力エラー", "CreatePlugin"), tr("デフォルト言語を指定してください。", "CreatePlugin"))
            return

        if not version:
            version = "1.0.0"

        # フォルダ名の決定
        if not folder_name:
            folder_name = plugin_id

        # フォルダ名の安全性の確認
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", folder_name):
            QMessageBox.warning(
                self,
                tr("入力エラー", "CreatePlugin"),
                tr("フォルダ名には半角英数字、アンダースコア(_)、ハイフン(-)、ピリオド(.)のみ使用できます。", "CreatePlugin")
            )
            return

        # 3. フォルダの作成先パスの設定
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        plugins_root = os.path.join(base_dir, "plugins")
        new_plugin_dir = os.path.join(plugins_root, folder_name)

        if os.path.exists(new_plugin_dir):
            QMessageBox.warning(
                self,
                tr("作成エラー", "CreatePlugin"),
                tr("すでに同名のフォルダが存在します: {folder}", "CreatePlugin").format(folder=folder_name)
            )
            return

        # 4. プラグインの雛形を作成
        try:
            # ディレクトリの作成
            os.makedirs(new_plugin_dir, exist_ok=True)
            os.makedirs(os.path.join(new_plugin_dir, "translations"), exist_ok=True)

            # 依存関係リストの構築
            deps = [d.strip() for d in deps_text.split(",") if d.strip()]

            # マニフェストファイルの辞書データ構築
            # 既存の仕様に沿って、翻訳ファイルを用いた構成を自動生成
            manifest_data = {
                "id": plugin_id,
                "name_key": f"{plugin_id}.name",
                "desc_key": f"{plugin_id}.desc",
                "version": version,
                "dependencies": deps
            }
            
            # マニフェストファイルの書き込み
            manifest_path = os.path.join(new_plugin_dir, "plugin_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=4, ensure_ascii=False)

            # デフォルト言語用の翻訳ファイルの作成
            translation_data = {
                f"{plugin_id}.name": plugin_name,
                f"{plugin_id}.desc": description
            }
            translation_path = os.path.join(new_plugin_dir, "translations", f"{default_lang}.json")
            with open(translation_path, "w", encoding="utf-8") as f:
                json.dump(translation_data, f, indent=4, ensure_ascii=False)

            self.created_plugin_id = plugin_id
            QMessageBox.information(
                self,
                tr("作成完了", "CreatePlugin"),
                tr("プラグインを作成しました。\nID: {id}\nフォルダ: {folder}", "CreatePlugin").format(id=plugin_id, folder=folder_name)
            )
            self.accept()

        except Exception as e:
            QMessageBox.critical(
                self,
                tr("システムエラー", "CreatePlugin"),
                tr("プラグインの作成に失敗しました:\n{error}", "CreatePlugin").format(error=e)
            )
