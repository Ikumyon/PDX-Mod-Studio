class DashboardTextParser:
    @staticmethod
    def parse(text: str) -> dict:
        lines = text.strip().split('\n')
        data = {
            "title": "",
            "meta": {},
            "metrics": {}
        }
        
        current_section = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # タイトルの取得
            if line.startswith("#"):
                data["title"] = line.lstrip("#").strip()
                continue
                
            # セクションの検出
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip().lower()
                continue
                
            # データのパース (key: value または key = value)
            delimiter = ":" if ":" in line else "=" if "=" in line else None
            if not delimiter:
                continue
                
            k, v = line.split(delimiter, 1)
            k = k.strip().lower()
            v = v.strip()
            
            # metrics セクションの場合
            if current_section == "metrics":
                # 規定されたスロットIDのみ格納
                if k in ("focuses", "events", "decisions", "total_loc", "untranslated_loc", "errors"):
                    try:
                        data["metrics"][k] = int(v)
                    except ValueError:
                        data["metrics"][k] = v
            else:
                # メタデータ項目
                if k in ("game", "version"):
                    data["meta"][k] = v
                    
        return data
