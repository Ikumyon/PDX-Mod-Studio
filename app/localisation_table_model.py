from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex

class LocalisationTableModel(QAbstractTableModel):
    """ローカライズデータのテーブル表示用モデル"""
    def __init__(self, loc_manager):
        super().__init__()
        self.loc_manager = loc_manager
        self.keys = []
        self.current_lang = "english"
        self.base_lang = "japanese" # 翻訳元

    def update_data(self):
        self.beginResetModel()
        self.keys = sorted(list(self.loc_manager.loc_data.keys()))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.keys)

    def columnCount(self, parent=QModelIndex()):
        return 3 # キー, 元言語, 対象言語

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return ["キー", f"元 ({self.base_lang})", f"対象 ({self.current_lang})"][section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        
        key = self.keys[index.row()]
        col = index.column()
        
        if role == Qt.DisplayRole or role == Qt.EditRole:
            if col == 0: return key
            if col == 1: return self.loc_manager.get_value(key, self.base_lang)
            if col == 2: return self.loc_manager.get_value(key, self.current_lang)
            
        if role == Qt.ForegroundRole:
            # 未翻訳の強調
            if col == 2 and not self.loc_manager.get_value(key, self.current_lang):
                return Qt.red
                
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or role != Qt.EditRole: return False
        
        key = self.keys[index.row()]
        if index.column() == 2:
            self.loc_manager.set_value(key, self.current_lang, value)
            self.dataChanged.emit(index, index)
            return True
        return False

    def flags(self, index):
        if not index.isValid(): return Qt.NoItemFlags
        if index.column() == 2:
            return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable
