import json
from pathlib import Path

class BaseExporter:
    """エクスポート処理の基底クラス"""
    def __init__(self, project_manager):
        self.pm = project_manager

    def export_all(self, target_dir):
        """プロジェクト内の全リソースをエクスポートする"""
        raise NotImplementedError("サブクラスで実装してください")

class JsonExporter(BaseExporter):
    """
    リソースをJSON形式で出力する汎用エクスポート。
    中間データとしての利用を想定。
    """
    def export_all(self, output_root):
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        
        # プロジェクト内の全リソースを走査
        data_dir = self.pm.project_root / "data"
        if not data_dir.exists(): return
        
        for file_path in data_dir.rglob("*.json"):
            # リソースをロード
            res_type, data = self.pm.load_resource(file_path)
            if data:
                # 出力先の決定
                rel_path = file_path.relative_to(data_dir)
                target_path = output_root / rel_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 保存
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        
        return True
