import yaml
import json
from pathlib import Path
import shutil

class ProjectManager:
    """
    プロジェクトの管理を行うクラス。
    ディレクトリ構造の維持、project.yaml の管理、データファイルの入出力を担当する。
    """
    def __init__(self):
        self.project_root = None
        self.project_data = {}
        self.is_loaded = False

    def create_new(self, root_path, name="New Project"):
        """新しいプロジェクトをディレクトリに作成する"""
        self.project_root = Path(root_path)
        self.project_root.mkdir(parents=True, exist_ok=True)
        
        # 基本構造の作成
        (self.project_root / "data").mkdir(exist_ok=True)
        (self.project_root / "data" / "events").mkdir(exist_ok=True)
        
        # project.yaml の作成
        self.project_data = {
            "name": name,
            "version": "1.0.0",
            "description": "PDX Mod Studio Project"
        }
        self.save_project_config()
        self.is_loaded = True
        return True

    def load(self, root_path):
        """既存のプロジェクトをロードする"""
        root = Path(root_path)
        config_file = root / "project.yaml"
        
        if not config_file.exists():
            return False
            
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                self.project_data = yaml.safe_load(f)
            self.project_root = root
            self.is_loaded = True
            
            # 必要なディレクトリがあるか確認し、なければ作成
            (self.project_root / "data").mkdir(exist_ok=True)
            (self.project_root / "data" / "events").mkdir(exist_ok=True)
            
            return True
        except Exception as e:
            print(f"プロジェクトのロードに失敗しました: {e}")
            return False

    def save_project_config(self):
        """project.yaml を保存する"""
        if not self.project_root:
            return
            
        config_file = self.project_root / "project.yaml"
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.safe_dump(self.project_data, f, allow_unicode=True)
        except Exception as e:
            print(f"プロジェクト設定の保存に失敗しました: {e}")

    def get_relative_path(self, absolute_path):
        """絶対パスをプロジェクトルートからの相対パスに変換する"""
        if not self.project_root:
            return absolute_path
        try:
            return Path(absolute_path).relative_to(self.project_root)
        except ValueError:
            return absolute_path

    def save_resource(self, file_path, resource_type, data):
        """リソースデータをJSONとして保存する"""
        payload = {
            "resource_type": resource_type,
            "data": data
        }
        
        target_path = Path(file_path)
        # 親ディレクトリの存在確認
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def load_resource(self, file_path):
        """リソースデータをJSONから読み込む。 (resource_type, data) のタプルを返す。"""
        target_path = Path(file_path)
        if not target_path.exists():
            return None, None
            
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
                return payload.get("resource_type"), payload.get("data")
        except Exception as e:
            print(f"リソースの読み込みに失敗しました: {e}")
            return None, None
    def get_all_ids(self, resource_type, schemas):
        """指定されたリソースタイプのすべてのIDを取得する"""
        if not self.project_root:
            return []
            
        schema = schemas.get(resource_type)
        if not schema:
            return []
            
        collection_path = self.project_root / schema.get('collection', '')
        if not collection_path.exists():
            return []
            
        ids = []
        for file_path in collection_path.glob("*.json"):
            res_type, data = self.load_resource(file_path)
            if res_type == resource_type and data:
                res_id = data.get('id')
                if res_id:
                    ids.append(res_id)
        return sorted(ids)
    def get_assets(self, sub_dir=None):
        """アセットディレクトリ内のファイル一覧を取得する"""
        if not self.project_root:
            return []
            
        asset_dir = self.project_root / "assets"
        if sub_dir:
            asset_dir = asset_dir / sub_dir
            
        if not asset_dir.exists():
            return []
            
        assets = []
        for file_path in asset_dir.rglob("*"):
            if file_path.is_file():
                # プロジェクトルートからの相対パス
                assets.append(file_path.relative_to(self.project_root))
        return sorted(assets)

    def import_asset(self, source_path, target_sub_dir=""):
        """外部ファイルをアセットディレクトリにインポートする"""
        if not self.project_root:
            return None
            
        source_path = Path(source_path)
        if not source_path.exists():
            return None
            
        target_dir = self.project_root / "assets" / target_sub_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = target_dir / source_path.name
        shutil.copy2(source_path, target_path)
        
        return target_path.relative_to(self.project_root)
