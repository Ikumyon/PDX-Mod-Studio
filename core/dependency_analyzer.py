from pathlib import Path

class DependencyGraph:
    """依存関係のグラフ構造を保持するクラス"""
    def __init__(self):
        self.forward_refs = {} # (type, id) -> set of (type, id)
        self.backward_refs = {} # (type, id) -> set of (type, id)
        self.all_nodes = set()

    def add_dependency(self, source, target):
        """source が target を参照している関係を追加"""
        self.all_nodes.add(source)
        self.all_nodes.add(target)
        
        if source not in self.forward_refs:
            self.forward_refs[source] = set()
        self.forward_refs[source].add(target)
        
        if target not in self.backward_refs:
            self.backward_refs[target] = set()
        self.backward_refs[target].add(source)

class DependencyAnalyzer:
    """
    プロジェクト全体のスキャンを行い、リソース間の依存関係を解析する。
    """
    def __init__(self, project_manager, schemas):
        self.pm = project_manager
        self.schemas = schemas

    def analyze(self):
        """プロジェクトを解析し DependencyGraph を返す"""
        graph = DependencyGraph()
        
        if not self.pm.is_loaded:
            return graph
            
        # 全リソースをスキャン
        for res_type, schema in self.schemas.items():
            collection_path = self.pm.project_root / schema.get('collection', '')
            if not collection_path.exists():
                continue
                
            for file_path in collection_path.glob("*.json"):
                t, data = self.pm.load_resource(file_path)
                if t == res_type and data:
                    res_id = data.get("id")
                    if not res_id: continue
                    
                    source = (res_type, res_id)
                    graph.all_nodes.add(source)
                    
                    # 参照フィールドを探す
                    for field in schema.get("fields", []):
                        f_type = field.get("type")
                        f_name = field.get("name")
                        target_type = field.get("target")
                        
                        if f_type == "ref" and target_type:
                            target_id = data.get(f_name)
                            if target_id:
                                graph.add_dependency(source, (target_type, target_id))
                                
                        elif f_type == "ref_list" and target_type:
                            target_ids = data.get(f_name)
                            if isinstance(target_ids, list):
                                for tid in target_ids:
                                    graph.add_dependency(source, (target_type, tid))
        return graph
