import os
import glob

class LocalisationScanner:
    def __init__(self, game_path, mod_path, language_id):
        self.game_path = game_path
        self.mod_path = mod_path
        self.language_id = language_id # 例: "l_japanese"

    def scan(self):
        """本体とMODのローカライズファイルをスキャンしてリストを返す"""
        results = []
        
        # 1. HOI4本体のスキャン
        if self.game_path and os.path.exists(self.game_path):
            loc_dir = os.path.join(self.game_path, "localisation")
            results.extend(self._find_yml_files(loc_dir, "hoi4"))
            
            # replace フォルダなども考慮（必要であれば）
            replace_dir = os.path.join(loc_dir, "replace")
            if os.path.exists(replace_dir):
                results.extend(self._find_yml_files(replace_dir, "hoi4"))

        # 2. MOD側のスキャン
        if self.mod_path and os.path.exists(self.mod_path):
            mod_loc_dir = os.path.join(self.mod_path, "localisation")
            results.extend(self._find_yml_files(mod_loc_dir, "mod"))
            
            mod_replace_dir = os.path.join(mod_loc_dir, "replace")
            if os.path.exists(mod_replace_dir):
                results.extend(self._find_yml_files(mod_replace_dir, "mod"))

        return results

    def _find_yml_files(self, root_dir, source_name):
        """指定ディレクトリ以下から対象言語のYMLファイルを探す"""
        found = []
        if not os.path.exists(root_dir):
            return found

        # パターン例: *_l_japanese.yml
        # HOI4の標準的な命名規則に基づき検索
        pattern = f"*_{self.language_id}.yml"
        
        for root, dirs, files in os.walk(root_dir):
            # globの代わりに fnmatch 的なマッチングを使用
            import fnmatch
            for filename in fnmatch.filter(files, pattern):
                full_path = os.path.join(root, filename)
                found.append({
                    "path": os.path.normpath(full_path),
                    "source": source_name,
                    "filename": filename
                })
        return found
