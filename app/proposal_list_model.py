from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex

class ProposalItem:
    """AIからの提案を表すクラス"""
    def __init__(self, title, description, res_type, data, target_path=None):
        self.title = title
        self.description = description
        self.res_type = res_type
        self.data = data
        self.target_path = target_path
        self.status = "レビュー待ち" # レビュー待ち, 採用済み, 却下, 一部採用

class ProposalListModel(QAbstractListModel):
    """提案リストの表示用モデル"""
    def __init__(self):
        super().__init__()
        self.proposals = []

    def add_proposal(self, proposal):
        self.beginInsertRows(QModelIndex(), len(self.proposals), len(self.proposals))
        self.proposals.append(proposal)
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self.proposals = []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.proposals)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.proposals)):
            return None
            
        proposal = self.proposals[index.row()]
        
        if role == Qt.DisplayRole:
            return f"[{proposal.status}] {proposal.title}"
            
        if role == Qt.UserRole:
            return proposal
            
        return None
