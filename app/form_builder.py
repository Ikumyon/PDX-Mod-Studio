import json
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QLineEdit, QPlainTextEdit, QSpinBox, 
    QCheckBox, QComboBox, QLabel, QVBoxLayout, QHBoxLayout,
    QSizePolicy, QPushButton, QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

class FieldWidgetFactory:
    """スキーマの型に基づいて適切なQtウィジェットを生成するファクトリ"""
    @staticmethod
    def create(field_schema):
        field_type = field_schema.get('type', 'string')
        name = field_schema.get('name')
        label_text = field_schema.get('label', name)
        
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        label = QLabel(label_text)
        label.setMinimumWidth(120)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(label)
        
        widget = None
        if field_type == 'string':
            widget = QLineEdit()
        elif field_type == 'text':
            widget = QPlainTextEdit()
            widget.setMaximumHeight(100)
        elif field_type == 'number':
            widget = QSpinBox()
            widget.setRange(-999999, 999999)
        elif field_type == 'boolean':
            widget = QCheckBox()
        elif field_type == 'enum':
            widget = QComboBox()
            options = field_schema.get('options', [])
            widget.addItems(options)
        elif field_type == 'ref':
            widget = QComboBox()
            widget.setEditable(True)
            # コンテキストがあれば選択肢を埋める
            pm = field_schema.get('_pm')
            schemas = field_schema.get('_schemas')
            target = field_schema.get('target')
            if pm and schemas and target:
                ids = pm.get_all_ids(target, schemas)
                widget.addItems([""] + ids)
        elif field_type == 'ref_list':
            widget = QPlainTextEdit()
            widget.setMaximumHeight(80)
            widget.setPlaceholderText("1行に1つのIDを入力")
        elif field_type == 'asset_ref':
            widget = QLineEdit()
            btn = QPushButton("参照...")
            btn.setFixedWidth(60)
            layout.addWidget(widget, 1)
            layout.addWidget(btn)
            
            pm = field_schema.get('_pm')
            
            def browse_asset():
                initial_dir = ""
                if pm and pm.project_root:
                    initial_dir = str(pm.project_root / "assets")
                    
                file_path, _ = QFileDialog.getOpenFileName(container, "アセットを選択", initial_dir)
                if file_path:
                    p = Path(file_path)
                    if pm and pm.project_root and (pm.project_root in p.parents or pm.project_root == p.parent):
                        rel_path = p.relative_to(pm.project_root)
                        widget.setText(str(rel_path))
                    else:
                        widget.setText(file_path)
            btn.clicked.connect(browse_asset)
            return container, widget
        elif field_type == 'localisation_ref':
            widget = QLineEdit()
            btn = QPushButton("鍵...")
            btn.setFixedWidth(40)
            layout.addWidget(widget, 1)
            layout.addWidget(btn)
            return container, widget
        elif field_type == 'script_block':
            widget = QPlainTextEdit()
            widget.setMinimumHeight(150)
            # 等幅フォントを設定
            font = QFont("Courier New")
            font.setStyleHint(QFont.Monospace)
            widget.setFont(font)
            widget.setPlaceholderText("# ここにスクリプトを記述...")
            
        if widget:
            widget.setProperty("field_type", field_type)
            layout.addWidget(widget, 1)
            return container, widget
        return None, None

class FormBuilder:
    """スキーマからフォームを構築し、データの同期を行うクラス"""
    def __init__(self, parent_layout, project_manager=None, schemas=None):
        self.layout = parent_layout
        self.pm = project_manager
        self.schemas = schemas
        self.widgets = {} # name -> widget
        
    def build(self, schema):
        """スキーマに基づいてウィジェットをレイアウトに配置する"""
        # 既存のウィジェットをクリア (最後のスペーサー以外)
        while self.layout.count() > 1:
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        self.widgets = {}
        for field in schema.get('fields', []):
            # コンテキストをフィールドスキーマに一時的に注入（ファクトリに渡すため）
            field_copy = dict(field)
            field_copy['_pm'] = self.pm
            field_copy['_schemas'] = self.schemas
            
            name = field_copy.get('name')
            container, widget = FieldWidgetFactory.create(field_copy)
            if container:
                # スペーサーの前に挿入
                self.layout.insertWidget(self.layout.count() - 1, container)
                self.widgets[name] = widget
                
    def get_data(self):
        """現在のフォーム入力値を辞書として取得する"""
        data = {}
        for name, widget in self.widgets.items():
            ftype = widget.property("field_type")
            
            if isinstance(widget, QLineEdit):
                data[name] = widget.text()
            elif isinstance(widget, QPlainTextEdit):
                if ftype == 'ref_list':
                    data[name] = [line.strip() for line in widget.toPlainText().split('\n') if line.strip()]
                else:
                    data[name] = widget.toPlainText()
            elif isinstance(widget, QSpinBox):
                data[name] = widget.value()
            elif isinstance(widget, QCheckBox):
                data[name] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                data[name] = widget.currentText()
        return data

    def set_data(self, data):
        """辞書データをフォームウィジェットに反映させる"""
        for name, value in data.items():
            widget = self.widgets.get(name)
            if not widget: continue
            
            if isinstance(widget, QLineEdit):
                widget.setText(str(value))
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText(str(value))
            elif isinstance(widget, QSpinBox):
                try:
                    widget.setValue(int(value))
                except: pass
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                index = widget.findText(str(value))
                if index >= 0:
                    widget.setCurrentIndex(index)
                else:
                    widget.setEditText(str(value))
            elif isinstance(widget, QPlainTextEdit) and isinstance(value, list):
                widget.setPlainText('\n'.join(map(str, value)))

    def save_to_json(self, file_path, resource_type=None):
        """現在のデータをJSONファイルとして保存する。resource_typeがあればラップする。"""
        data = self.get_data()
        payload = data
        if resource_type:
            payload = {
                "resource_type": resource_type,
                "data": data
            }
            
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Data saved to {file_path}")

    def load_from_json(self, file_path):
        """JSONファイルからデータを読み込み、フォームに反映させる。ラップされていれば展開する。"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
                
                # ラップされているかチェック
                if isinstance(payload, dict) and "resource_type" in payload and "data" in payload:
                    data = payload["data"]
                else:
                    data = payload
                    
                self.set_data(data)
                print(f"Data loaded from {file_path}")
                return payload # 呼び出し側が resource_type を知る必要がある場合のために返す
        except Exception as e:
            print(f"Failed to load JSON: {e}")
            return None
