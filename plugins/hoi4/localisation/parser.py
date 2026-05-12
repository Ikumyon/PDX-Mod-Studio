import os
import re


class LocalisationParser:
    def __init__(self):
        self.entry_re = re.compile(r'^\s*([A-Za-z0-9._-]+):(\d+)?\s*"(.*)"\s*(#.*)?$')
        self.header_re = re.compile(r'^\s*([A-Za-z0-9._-]+):\s*$')

    def parse(self, file_path, expected_language=None):
        data = {
            "language": None,
            "entries": [],
            "errors": [],
        }

        if not os.path.exists(file_path):
            data["errors"].append({"line": 0, "content": "", "reason": "File not found"})
            return data

        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            data["errors"].append({"line": 0, "content": "", "reason": "Invalid encoding: expected UTF-8 or UTF-8 BOM"})
            return data
        except Exception as e:
            data["errors"].append({"line": 0, "content": "", "reason": f"Failed to read file: {e}"})
            return data

        header_found = False
        for line_no, line in enumerate(lines, 1):
            clean_line = line.strip()
            if not clean_line or clean_line.startswith("#"):
                continue

            if not header_found:
                match = self.header_re.match(clean_line)
                if match:
                    data["language"] = match.group(1)
                    header_found = True
                    if expected_language and data["language"] != expected_language:
                        data["errors"].append({
                            "line": line_no,
                            "content": clean_line,
                            "reason": f"Language header mismatch: expected {expected_language}",
                        })
                    continue

                data["errors"].append({
                    "line": line_no,
                    "content": clean_line,
                    "reason": "Missing or invalid language header",
                })
                continue

            match = self.entry_re.match(clean_line)
            if match:
                data["entries"].append({
                    "key": match.group(1),
                    "value": match.group(3),
                    "line": line_no,
                })
            else:
                data["errors"].append({
                    "line": line_no,
                    "content": clean_line,
                    "reason": "Invalid entry format",
                })

        if not header_found:
            data["errors"].append({"line": 0, "content": "", "reason": "Missing language header"})

        return data
