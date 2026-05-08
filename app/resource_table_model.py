import json
from pathlib import Path
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex

class ResourceTableModel(QAbstractTableModel):
    """
    リソース（JSONファイル群）をテーブル形式で表示するためのモデル。
    """
    def __init__(self, schema, project_manager):
        super().__init__()
        self.schema = schema
        self.pm = project_manager
        self.fields = schema.get('fields', [])
        self.column_names = [f.get('name') for f in self.fields]
        self.column_labels = [f.get('label', f.get('name')) for f in self.fields]
        
        self.all_data = [] # List of { 'data': dict, 'path': Path }
        self.display_data = [] # Filtered list

    def load_data(self):
        """ディレクトリからJSONファイルを読み込んでモデルを更新する"""
        if not self.pm.is_loaded:
            return
            
        collection_path = self.pm.project_root / self.schema.get('collection', '')
        if not collection_path.exists():
            collection_path.mkdir(parents=True, exist_ok=True)
            
        self.beginResetModel()
        self.all_data = []
        
        # JSONファイルをスキャン
        for file_path in collection_path.glob("*.json"):
            res_type, data = self.pm.load_resource(file_path)
            if res_type == self.schema.get('resource_type'):
                self.all_data.append({
                    'data': data,
                    'path': file_path
                })
        
        self.display_data = list(self.all_data)
        self.endResetModel()

    def filter(self, text):
        """テキストでデータを絞り込む"""
        self.beginResetModel()
        if not text:
            self.display_data = list(self.all_data)
        else:
            text = text.lower()
            self.display_data = []
            for item in self.all_data:
                # いずれかのフィールドに含まれているかチェック
                match = False
                for value in item['data'].values():
                    if text in str(value).lower():
                        match = True
                        break
                if match:
                    self.display_data.append(item)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.display_data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.column_names)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.display_data)):
            return None
            
        if role == Qt.DisplayRole:
            row_data = self.display_data[index.row()]['data']
            col_name = self.column_names[index.column()]
            return str(row_data.get(col_name, ""))
            
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(self.column_labels):
                return self.column_labels[section]
        return None

    def get_path(self, row):
        """指定した行のファイルパスを取得"""
        if 0 <= row < len(self.display_data):
            return self.display_data[row]['path']
        return None

    def get_resource_data(self, row):
        """指定した行のデータ自体を取得"""
        if 0 <= row < len(self.display_data):
            return self.display_data[row]['data']
        return None
