import os

from plugins.hoi4.localisation.parser import LocalisationParser
from plugins.hoi4.localisation.scanner import LocalisationScanner


class LocalisationRegistry:
    def __init__(self):
        self.key_registry = {}
        self.file_registry = []
        self.file_key_index = {}
        self.file_errors = {}
        self.language_id = None
        self.parser = LocalisationParser()
        self._ignore_paths = set()

    def rebuild(self, game_path, mod_path, language_id):
        self.key_registry = {}
        self.file_registry = []
        self.file_key_index = {}
        self.file_errors = {}
        self.language_id = language_id

        scanner = LocalisationScanner(game_path, mod_path, language_id)
        files = scanner.scan()
        self.file_registry = files

        for file_info in [f for f in files if f["source"] == "hoi4"]:
            self._parse_and_register(file_info)
        for file_info in [f for f in files if f["source"] == "mod"]:
            self._parse_and_register(file_info)

        print(f"Registry rebuilt: {len(self.key_registry)} keys.")

    def update_file(self, path, source):
        path = os.path.normpath(path)
        if path in self._ignore_paths:
            return

        self.remove_file_entries(path)

        file_info = {
            "path": path,
            "source": source,
            "filename": os.path.basename(path),
        }
        self._parse_and_register(file_info)

        if not any(os.path.normpath(f["path"]) == path for f in self.file_registry):
            self.file_registry.append(file_info)

    def remove_file_entries(self, path):
        path = os.path.normpath(path)
        keys = self.file_key_index.pop(path, set())
        for key in keys:
            entries = self.key_registry.get(key, [])
            entries = [entry for entry in entries if os.path.normpath(entry["file"]) != path]
            if entries:
                self.key_registry[key] = entries
            else:
                self.key_registry.pop(key, None)

        self.file_errors.pop(path, None)
        self.file_registry = [f for f in self.file_registry if os.path.normpath(f["path"]) != path]

    def set_ignore_path(self, path, ignore=True):
        path = os.path.normpath(path)
        if ignore:
            self._ignore_paths.add(path)
        else:
            self._ignore_paths.discard(path)

    def _parse_and_register(self, file_info):
        path = os.path.normpath(file_info["path"])
        source = file_info["source"]
        result = self.parser.parse(path, self.language_id)

        if result["errors"]:
            self.file_errors[path] = result["errors"]

        seen_in_file = set()
        is_writable = source == "mod"
        for item in result["entries"]:
            key = item["key"]
            entry = {
                "key": key,
                "value": item["value"],
                "file": path,
                "source": source,
                "writable": is_writable,
                "line": item.get("line"),
            }
            self.key_registry.setdefault(key, []).append(entry)
            seen_in_file.add(key)

        self.file_key_index[path] = seen_in_file

    def search_key_status(self, key):
        key = (key or "").strip()
        if not key:
            return "not_found", None

        entries = self.key_registry.get(key, [])
        if not entries:
            return "not_found", None

        mod_entries = [entry for entry in entries if entry["source"] == "mod"]
        hoi4_entries = [entry for entry in entries if entry["source"] == "hoi4"]

        if len(mod_entries) > 1:
            return "duplicate", self._with_candidates(mod_entries[0], mod_entries, hoi4_entries)

        if len(mod_entries) == 1:
            return "exists_in_mod", self._with_candidates(mod_entries[0], mod_entries, hoi4_entries)

        if hoi4_entries:
            return "exists_in_hoi4", self._with_candidates(hoi4_entries[0], [], hoi4_entries)

        return "unknown", self._with_candidates(entries[0], mod_entries, hoi4_entries)

    def _with_candidates(self, selected, mod_entries, hoi4_entries):
        entry = dict(selected)
        entry["candidates"] = list(mod_entries) + list(hoi4_entries)
        entry["mod_candidates"] = list(mod_entries)
        entry["hoi4_candidates"] = list(hoi4_entries)
        return entry

    def get_file_errors(self, file_path):
        return self.file_errors.get(os.path.normpath(file_path), [])
