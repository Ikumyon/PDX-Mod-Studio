import re
from pathlib import Path

class LocalisationManager:
    """Paradox形式のYAMLローカライズファイルを管理するクラス"""
    def __init__(self, project_root):
        self.project_root = project_root
        self.loc_data = {} # key -> {lang: text}
        self.languages = ["english", "japanese", "german", "french", "spanish"]

    def load_all(self):
        """プロジェクト内の全ローカライズファイルを読み込む"""
        if not self.project_root: return
        
        loc_dir = self.project_root / "localisation"
        if not loc_dir.exists(): return
        
        self.loc_data = {}
        for file_path in loc_dir.rglob("*.yml"):
            self.load_file(file_path)

    def load_file(self, path):
        """1つのファイルを読み込む"""
        lang = "english"
        # ファイル名や中身から言語を特定 (l_english: 等)
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                content = f.read()
                
            lines = content.splitlines()
            if not lines: return
            
            # 最初の行で言語を特定
            header_match = re.match(r"^l_(\w+):", lines[0])
            if header_match:
                lang = header_match.group(1)
                
            for line in lines[1:]:
                # キーと値を抽出 (KEY:0 "Value")
                match = re.match(r"^\s*([\w\.\-]+):(\d*)\s*\"(.*)\"", line)
                if match:
                    key = match.group(1)
                    value = match.group(3)
                    
                    if key not in self.loc_data:
                        self.loc_data[key] = {}
                    self.loc_data[key][lang] = value
        except Exception as e:
            print(f"ローカライズファイルの読み込み失敗: {path} - {e}")

    def save_all(self):
        """現在のデータを各言語ファイルに保存する"""
        if not self.project_root: return
        
        loc_dir = self.project_root / "localisation"
        loc_dir.mkdir(parents=True, exist_ok=True)
        
        for lang in self.languages:
            # 簡略化のため1言語1ファイルにまとめる (本来はファイル構造を維持すべき)
            file_path = loc_dir / f"messages_l_{lang}.yml"
            self.save_language_file(file_path, lang)

    def save_language_file(self, path, lang):
        """特定の言語のファイルを作成"""
        lines = [f"l_{lang}:"]
        for key, vals in self.loc_data.items():
            if lang in vals:
                lines.append(f' {key}:0 "{vals[lang]}"')
        
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(lines) + "\n")

    def get_value(self, key, lang="english"):
        return self.loc_data.get(key, {}).get(lang, "")

    def set_value(self, key, lang, value):
        if key not in self.loc_data:
            self.loc_data[key] = {}
        self.loc_data[key][lang] = value
