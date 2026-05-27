from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QDialogButtonBox
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

        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget)

        # 項目を追加
        # 1. 自動判別
        item_auto = QListWidgetItem(tr("MainWindow", "自動判別"))
        item_auto.setData(Qt.ItemDataRole.UserRole, "auto")
        self.list_widget.addItem(item_auto)
        if current_mode == "auto":
            self.list_widget.setCurrentItem(item_auto)

        # 2. プレーンテキスト
        item_plain = QListWidgetItem(tr("MainWindow", "プレーンテキスト"))
        item_plain.setData(Qt.ItemDataRole.UserRole, "plain_text")
        self.list_widget.addItem(item_plain)
        if current_mode == "plain_text":
            self.list_widget.setCurrentItem(item_plain)

        # 3. 各種要素定義
        for elem in available_elements:
            name = getattr(elem, "name", elem.id)
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, elem)
            self.list_widget.addItem(item)
            # 現在のモードが Element オブジェクトでIDが一致する場合
            if hasattr(current_mode, "id") and current_mode.id == elem.id:
                self.list_widget.setCurrentItem(item)

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

    def _on_item_double_clicked(self, item):
        self.selected_mode = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_accepted(self):
        item = self.list_widget.currentItem()
        if item:
            self.selected_mode = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
