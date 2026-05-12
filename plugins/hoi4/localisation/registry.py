import os
from plugins.hoi4.localisation.scanner import LocalisationScanner
from plugins.hoi4.localisation.parser import LocalisationParser

class LocalisationRegistry:
    def __init__(self):
        self.key_registry = {}  # { key: { "value": str, "file": str, "source": str, "writable": bool } }
        self.key_sources = {}   # { key: set(["hoi4", "mod"]) } 重複判定用
        self.file_registry = [] # [ { "path": str, "source": str, "filename": str } ]
        self.file_errors = {}   # { path: [errors] }
        self.parser = LocalisationParser()
        self._ignore_paths = set() # 監視を一時的に無視するパス

    def rebuild(self, game_path, mod_path, language_id):
        """レジストリをゼロから再構築する"""
        self.key_registry = {}
        self.key_sources = {}
        self.file_registry = []
        self.file_errors = {}
        
        scanner = LocalisationScanner(game_path, mod_path, language_id)
        files = scanner.scan()
        self.file_registry = files

        # 本体 -> MOD の順に処理
        for file_info in [f for f in files if f["source"] == "hoi4"]:
            self._parse_and_register(file_info)
        for file_info in [f for f in files if f["source"] == "mod"]:
            self._parse_and_register(file_info)

        print(f"Registry rebuilt: {len(self.key_registry)} keys.")

    def update_file(self, path, source):
        """特定のファイルを再パースしてレジストリを更新する（差分更新）"""
        if path in self._ignore_paths:
            return
            
        # 1. 既存のこのファイル由来のキーを削除
        self.remove_file_entries(path)
        
        # 2. 再パースして登録
        file_info = {
            "path": path,
            "source": source,
            "filename": os.path.basename(path)
        }
        self._parse_and_register(file_info)
        
        # 3. file_registry の更新（なければ追加）
        if not any(f["path"] == path for f in self.file_registry):
            self.file_registry.append(file_info)

    def remove_file_entries(self, path):
        """特定のファイルに関連するキー情報をレジストリから削除する"""
        keys_to_remove = [k for k, v in self.key_registry.items() if v["file"] == path]
        for k in keys_to_remove:
            del self.key_registry[k]
            if k in self.key_sources:
                self.key_sources[k].discard(os.path.basename(os.path.dirname(os.path.dirname(path)))) # 簡易的
                # 正確には source 名で管理すべきだが、一旦単純化
                if not self.key_sources[k]:
                    del self.key_sources[k]
        
        if path in self.file_errors:
            del self.file_errors[path]
        
        self.file_registry = [f for f in self.file_registry if f["path"] != path]

    def set_ignore_path(self, path, ignore=True):
        """特定パスの監視イベントを一時的に無視するように設定する"""
        if ignore:
            self._ignore_paths.add(path)
        else:
            self._ignore_paths.discard(path)

    def _parse_and_register(self, file_info):
        """個別のファイルをパースしてレジストリに登録する"""
        result = self.parser.parse(file_info["path"])
        path = file_info["path"]
        source = file_info["source"]
        
        # エラーを保持
        if result["errors"]:
            self.file_errors[path] = result["errors"]
        
        is_writable = (source == "mod")
        for key, text in result["entries"].items():
            # キー情報を登録（MOD優先で上書き）
            self.key_registry[key] = {
                "value": text,
                "file": path,
                "source": source,
                "writable": is_writable
            }
            # ソースの存在記録
            if key not in self.key_sources:
                self.key_sources[key] = set()
            self.key_sources[key].add(source)

    def search_key_status(self, key):
        """
        キーの状態を判定して返す
        戻り値: (status_code, info_dict)
        """
        sources = self.key_sources.get(key, set())
        entry = self.key_registry.get(key)
        
        # 1. 未登録
        if not entry:
            return "not_found", None

        # 2. 重複 (MODと本体の両方に存在)
        if "mod" in sources and "hoi4" in sources:
            return "duplicate", entry

        # 3. MODに存在
        if entry["source"] == "mod":
            return "exists_in_mod", entry

        # 4. HOI4本体にだけ存在
        if entry["source"] == "hoi4":
            return "exists_in_hoi4", entry

        return "unknown", entry

    def get_file_errors(self, file_path):
        """特定のファイルに関連するエラーを取得する"""
        return self.file_errors.get(file_path, [])
