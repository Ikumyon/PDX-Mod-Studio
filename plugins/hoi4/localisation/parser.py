import re
import os

class LocalisationParser:
    def __init__(self):
        # キー抽出用の正規表現
        # 形式:  key:0 "text" または key:"text"
        # 先頭の空白を許容し、キー名、バージョン(任意)、ダブルクォート内のテキストをキャプチャ
        self.entry_re = re.compile(r'^\s*([a-zA-Z0-9._-]+):(\d+)?\s*"(.*)"\s*$')
        self.header_re = re.compile(r'^([a-zA-Z0-9._-]+):\s*$')

    def parse(self, file_path):
        """YMLファイルをパースして結果を返す"""
        data = {
            "language": None,
            "entries": {}, # {key: text}
            "errors": []   # [{"line": i, "content": str, "reason": str}]
        }

        if not os.path.exists(file_path):
            data["errors"].append({"line": 0, "content": "", "reason": "File not found"})
            return data

        try:
            # BOM付きUTF-8に対応するため utf-8-sig を使用
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            data["errors"].append({"line": 0, "content": "", "reason": "Invalid encoding: Must be UTF-8 with BOM"})
            return data
        except Exception as e:
            data["errors"].append({"line": 0, "content": "", "reason": f"Failed to read file: {e}"})
            return data

        header_found = False
        for i, line in enumerate(lines, 1):
            clean_line = line.strip()
            
            # 空行またはコメント行を無視
            if not clean_line or clean_line.startswith('#'):
                continue

            # 1. ヘッダーの探索
            if not header_found:
                match = self.header_re.match(clean_line)
                if match:
                    data["language"] = match.group(1)
                    header_found = True
                    continue
                else:
                    # まだヘッダーが見つかっていない場合のエラー（最初の有効な行がヘッダーでない）
                    data["errors"].append({
                        "line": i, 
                        "content": clean_line, 
                        "reason": "Missing or invalid language header (expected 'l_language:') at start of file"
                    })
                    # ヘッダーが見つかるまでキー解析は行わない
                    continue

            # 2. キーと本文の抽出
            match = self.entry_re.match(clean_line)
            if match:
                key = match.group(1)
                text = match.group(3)
                data["entries"][key] = text
            else:
                # 壊れた行として記録
                data["errors"].append({
                    "line": i, 
                    "content": clean_line, 
                    "reason": "Invalid entry format (expected ' key:0 \"text\"')"
                })

        return data
