class ContextBuilder:
    """AIに渡すためのプロジェクト・リソース文脈を構築するクラス"""
    def __init__(self, project_manager, schemas):
        self.pm = project_manager
        self.schemas = schemas

    def build_resource_context(self, res_type, data):
        """現在編集中のリソースの文脈を文字列化する"""
        schema = self.schemas.get(res_type, {})
        label = schema.get('label', res_type)
        
        context = f"現在編集中のリソース: {label} ({res_type})\n"
        context += "現在のデータ:\n"
        for k, v in data.items():
            context += f"- {k}: {v}\n"
        return context

    def build_project_context(self):
        """プロジェクト全体の状態（ファイル構成など）を文脈にする"""
        if not self.pm.is_loaded:
            return "プロジェクト未ロード"
            
        context = f"プロジェクト名: {self.pm.project_data.get('name')}\n"
        # 各リソースの件数などを入れると良い
        return context
