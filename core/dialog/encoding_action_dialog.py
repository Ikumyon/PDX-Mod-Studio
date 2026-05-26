from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

tr = QCoreApplication.translate


class EncodingActionDialog(QDialog):
    def __init__(self, parent, current_encoding, encoding_options, format_encoding_label):
        super().__init__(parent)
        self.selected_action = None
        self.selected_encoding = None
        self.current_encoding = current_encoding
        self.encoding_options = encoding_options
        self._format_encoding_label = format_encoding_label
        self.setWindowTitle(tr("MainWindow", "文字コード"))
        self.resize(560, 420)

        root_layout = QVBoxLayout(self)

        self.title_label = QLabel(tr("MainWindow", "アクションの選択"))
        root_layout.addWidget(self.title_label)

        self.stack = QStackedWidget(self)
        root_layout.addWidget(self.stack, 1)

        self.action_page = self._create_scroll_page(
            [
                (tr("MainWindow", "エンコード付きで再度開く"), self._on_choose_reopen),
                (tr("MainWindow", "エンコード付きで保存"), self._on_choose_save),
            ]
        )
        self.encoding_page = self._create_scroll_page(self._build_encoding_buttons())

        self.stack.addWidget(self.action_page)
        self.stack.addWidget(self.encoding_page)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        self.back_button = QPushButton(tr("MainWindow", "戻る"))
        self.back_button.clicked.connect(self._go_back)
        self.back_button.setEnabled(False)
        footer_layout.addWidget(self.back_button)
        self.cancel_button = QPushButton(tr("MainWindow", "キャンセル"))
        self.cancel_button.clicked.connect(self.reject)
        footer_layout.addWidget(self.cancel_button)
        root_layout.addLayout(footer_layout)

    def _create_scroll_page(self, button_specs):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)

        for label, handler in button_specs:
            button = QPushButton(label)
            button.setMinimumHeight(40)
            button.clicked.connect(handler)
            container_layout.addWidget(button)

        container_layout.addStretch()
        scroll.setWidget(container)
        page_layout.addWidget(scroll)
        return page

    def _build_encoding_buttons(self):
        specs = []
        current_label = self._format_encoding_label(self.current_encoding)
        for encoding in self.encoding_options:
            label = self._format_encoding_label(encoding)
            if label == current_label:
                label = f"{label} *"
            specs.append((label, lambda checked=False, e=encoding: self._on_choose_encoding(e)))
        return specs

    def _on_choose_reopen(self):
        self.selected_action = "reopen"
        self.title_label.setText(tr("MainWindow", "エンコード付きで再度開く"))
        self.stack.setCurrentWidget(self.encoding_page)
        self.back_button.setEnabled(True)

    def _on_choose_save(self):
        self.selected_action = "save"
        self.title_label.setText(tr("MainWindow", "エンコード付きで保存"))
        self.stack.setCurrentWidget(self.encoding_page)
        self.back_button.setEnabled(True)

    def _on_choose_encoding(self, encoding):
        self.selected_encoding = encoding
        self.accept()

    def _go_back(self):
        self.selected_action = None
        self.selected_encoding = None
        self.title_label.setText(tr("MainWindow", "アクションの選択"))
        self.stack.setCurrentWidget(self.action_page)
        self.back_button.setEnabled(False)
