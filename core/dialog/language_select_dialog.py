from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QDialogButtonBox,
    QCheckBox
)

tr = QCoreApplication.translate

class LanguageSelectDialog(QDialog):
    def __init__(self, parent, current_mode, available_elements):
        """
        current_mode: "auto", "plain_text", もしくは Element オブジェクト
        available_elements: プラグインに登録されている要素オブジェクトのリスト
        """
        super().__init__(parent)
        self.selected_mode = None
        self.setWindowTitle(tr("MainWindow", "言語モードの選択"))
        self.resize(400, 350)

        layout = QVBoxLayout(self)

        label = QLabel(tr("MainWindow", "適用する言語モードを選択してください:"))
        layout.addWidget(label)

        # 自動判別チェックボックスを追加
        self.auto_checkbox = QCheckBox(tr("MainWindow", "自動判別"), self)
        self.auto_checkbox.stateChanged.connect(self._on_auto_changed)
        layout.addWidget(self.auto_checkbox)

        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget)

        # 1. プレーンテキスト
        item_plain = QListWidgetItem(tr("MainWindow", "プレーンテキスト"))
        item_plain.setData(Qt.ItemDataRole.UserRole, "plain_text")
        self.list_widget.addItem(item_plain)

        # 2. 各種要素定義 (一時的に読み込まないようにコメントアウト)
        #ここにあった

        # 初期状態の設定
        if current_mode == "auto":
            self.auto_checkbox.setChecked(True)
            self.list_widget.setEnabled(False)
            self.list_widget.setCurrentItem(item_plain)
        else:
            self.auto_checkbox.setChecked(False)
            self.list_widget.setEnabled(True)
            if current_mode == "plain_text":
                self.list_widget.setCurrentItem(item_plain)

        # ダブルクリックで決定
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)

        # ボタン
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self
        )
        self.button_box.accepted.connect(self._on_accepted)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_auto_changed(self, state):
        is_auto = (state == Qt.CheckState.Checked.value)
        self.list_widget.setEnabled(not is_auto)

    def _on_item_double_clicked(self, item):
        if not self.auto_checkbox.isChecked():
            self.selected_mode = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def _on_accepted(self):
        if self.auto_checkbox.isChecked():
            self.selected_mode = "auto"
        else:
            item = self.list_widget.currentItem()
            if item:
                self.selected_mode = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

