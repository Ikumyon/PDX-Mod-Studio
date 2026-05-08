from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor

class LogTableModel(QAbstractTableModel):
    """ログや検査結果をテーブル表示するためのモデル"""
    def __init__(self):
        super().__init__()
        self.items = [] # List of dicts
        self.headers = ["レベル", "メッセージ", "リソース", "ID", "フィールド", "ファイル"]

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def add_item(self, item):
        self.beginInsertRows(QModelIndex(), len(self.items), len(self.items))
        self.items.append(item)
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self.items = []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.items)):
            return None
            
        item = self.items[index.row()]
        col = index.column()
        
        if role == Qt.DisplayRole:
            if col == 0: return item.get("level")
            if col == 1: return item.get("message")
            if col == 2: return item.get("res_type")
            if col == 3: return item.get("res_id")
            if col == 4: return item.get("field")
            if col == 5: return Path(item.get("file_path")).name if item.get("file_path") else ""
            
        if role == Qt.ForegroundRole:
            level = item.get("level")
            if level == "Error": return QColor("red")
            if level == "Warning": return QColor("orange")
            if level == "Info": return QColor("blue")
            
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None
from pathlib import Path
