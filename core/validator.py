from pathlib import Path

class ValidationIssue:
    """検査結果の1項目を表すクラス"""
    def __init__(self, level, message, res_type=None, res_id=None, field=None, file_path=None):
        self.level = level # 'Error', 'Warning', 'Info'
        self.message = message
        self.res_type = res_type
        self.res_id = res_id
        self.field = field
        self.file_path = file_path

    def to_dict(self):
        return {
            "level": self.level,
            "message": self.message,
            "res_type": self.res_type,
            "res_id": self.res_id,
            "field": self.field,
            "file_path": str(self.file_path) if self.file_path else ""
        }

class ValidationEngine:
    """
    リソースの整合性を検査するエンジン。
    スキーマの定義に基づいて汎用的なバリデーションを行う。
    """
    def __init__(self, project_manager, schemas):
        self.pm = project_manager
        self.schemas = schemas
        self.all_ids_cache = {} # res_type -> set of IDs

    def refresh_id_cache(self):
        """プロジェクト内のすべてのIDをキャッシュする（重い処理）"""
        self.all_ids_cache = {}
        for res_type in self.schemas.keys():
            ids = self.pm.get_all_ids(res_type, self.schemas)
            self.all_ids_cache[res_type] = set(ids)

    def validate_data(self, res_type, data, file_path=None):
        """単一のデータオブジェクトを検査する"""
        issues = []
        schema = self.schemas.get(res_type)
        if not schema:
            return [ValidationIssue("Error", f"スキーマが見つかりません: {res_type}")]

        res_id = data.get("id", "Unknown")
        fields = schema.get("fields", [])
        
        for field in fields:
            name = field.get("name")
            label = field.get("label", name)
            value = data.get(name)
            f_type = field.get("type", "string")
            
            # 1. 必須チェック
            if field.get("required") and (value is None or value == ""):
                issues.append(ValidationIssue("Error", f"必須項目 '{label}' が未入力です", res_type, res_id, name, file_path))

            # 2. 型チェック (簡易)
            if f_type == "number" and value is not None:
                try:
                    float(value)
                except ValueError:
                    issues.append(ValidationIssue("Error", f"'{label}' は数値である必要があります", res_type, res_id, name, file_path))

            # 3. 参照チェック (ref / ref_list)
            if f_type == "ref" and value:
                target_type = field.get("target")
                if target_type:
                    valid_ids = self.all_ids_cache.get(target_type)
                    # キャッシュになければ都度取得（キャッシュが古い可能性を考慮）
                    if valid_ids is None:
                        valid_ids = set(self.pm.get_all_ids(target_type, self.schemas))
                        self.all_ids_cache[target_type] = valid_ids
                        
                    if value not in valid_ids:
                        issues.append(ValidationIssue("Warning", f"参照先のリソース '{value}' ({target_type}) が見つかりません", res_type, res_id, name, file_path))
            
            if f_type == "ref_list" and isinstance(value, list):
                target_type = field.get("target")
                if target_type:
                    valid_ids = self.all_ids_cache.get(target_type)
                    if valid_ids is None:
                        valid_ids = set(self.pm.get_all_ids(target_type, self.schemas))
                        self.all_ids_cache[target_type] = valid_ids
                        
                    for v in value:
                        if v not in valid_ids:
                            issues.append(ValidationIssue("Warning", f"参照先のリソース '{v}' ({target_type}) が見つかりません", res_type, res_id, name, file_path))

            # 4. 文字列長チェック
            max_len = field.get("max_length")
            if max_len and isinstance(value, str) and len(value) > max_len:
                issues.append(ValidationIssue("Warning", f"'{label}' が長すぎます (最大 {max_len} 文字)", res_type, res_id, name, file_path))

        return issues

    def validate_project(self):
        """プロジェクト全体のすべてのファイルを検査する"""
        all_issues = []
        self.refresh_id_cache()
        
        # ID重複チェック
        for res_type, ids in self.all_ids_cache.items():
            # get_all_ids は glob して集めるが、同一ディレクトリ内のファイル間での重複をチェックする必要がある
            # 実際には get_all_ids は単純なリストを返すので、中身を精査する
            schema = self.schemas.get(res_type)
            collection_path = self.pm.project_root / schema.get('collection', '')
            
            id_to_files = {}
            for file_path in collection_path.glob("*.json"):
                t, data = self.pm.load_resource(file_path)
                if t == res_type and data:
                    rid = data.get("id")
                    if rid:
                        if rid in id_to_files:
                            id_to_files[rid].append(file_path)
                        else:
                            id_to_files[rid] = [file_path]
            
            for rid, files in id_to_files.items():
                if len(files) > 1:
                    file_names = ", ".join([f.name for f in files])
                    all_issues.append(ValidationIssue("Error", f"ID '{rid}' が重複しています: {file_names}", res_type, rid))

        # 各ファイルの内容を詳細検査
        for res_type, schema in self.schemas.items():
            collection_path = self.pm.project_root / schema.get('collection', '')
            for file_path in collection_path.glob("*.json"):
                t, data = self.pm.load_resource(file_path)
                if t == res_type and data:
                    all_issues.extend(self.validate_data(res_type, data, file_path))
                    
        return all_issues
