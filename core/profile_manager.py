import os
import json
import importlib.util

class ModElement:
    def __init__(
        self,
        id,
        name,
        path,
        extension,
        is_folder=False,
        icon_path=None,
        template=None,
        document_type=None,
        path_globs=None,
        form=None,
        logic=None,
        parser=None,
        parser_entry=None,
        schema=None,
        element_dir=None,
    ):
        self.id = id
        self.name = name
        self.path = path
        self.extension = extension
        self.is_folder = is_folder
        self.icon_path = icon_path
        self.template = template
        self.document_type = document_type
        self.path_globs = path_globs or []
        self.form = form
        self.logic = logic
        self.parser = parser
        self.parser_entry = parser_entry
        self.schema = schema
        self.element_dir = element_dir

    def __repr__(self):
        return f"<ModElement {self.name} ({self.path})>"

class Profile:
    def __init__(self, id, name, version, path, icon_path=None, raw=None):
        self.id = id
        self.name = name
        self.version = version
        self.path = path
        self.icon_path = icon_path
        self.raw = raw or {}
        self.elements = [] # ModElementのリスト

    def __repr__(self):
        return f"<Profile {self.name} ({self.id})>"

class ProfileManager:
    def __init__(self, profiles_dir):
        self.profiles_dir = profiles_dir
        self.profiles = []

    def load_profiles(self):
        self.profiles = []
        if not os.path.exists(self.profiles_dir):
            return []

        for item in os.listdir(self.profiles_dir):
            item_path = os.path.join(self.profiles_dir, item)
            if os.path.isdir(item_path):
                config_path = os.path.join(item_path, "profile.json")
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            
                            icon_name = data.get("icon")
                            icon_path = os.path.join(item_path, icon_name) if icon_name else None
                            
                            profile = Profile(
                                id=data.get("id", item),
                                name=data.get("name", item),
                                version=data.get("version", "unknown"),
                                path=item_path,
                                icon_path=icon_path,
                                raw=data
                            )
                            
                            # 要素（ModElements）のロード
                            self._load_elements(profile)
                            
                            self.profiles.append(profile)
                    except Exception as e:
                        print(f"Failed to load profile from {config_path}: {e}")
        
        return self.profiles

    def _load_elements(self, profile):
        """プロファイルフォルダ内のサブフォルダを走査して要素をロードする"""
        for item in os.listdir(profile.path):
            element_dir = os.path.join(profile.path, item)
            if os.path.isdir(element_dir):
                element_config_path = os.path.join(element_dir, "config.json")
                if os.path.exists(element_config_path):
                    try:
                        with open(element_config_path, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                            icon_name = config.get("icon")
                            icon_path = os.path.join(element_dir, icon_name) if icon_name else None
                            
                            element = ModElement(
                                id=item,
                                name=config.get("name", item),
                                path=config.get("path", ""),
                                extension=config.get("extension", ".txt"),
                                is_folder=config.get("is_folder", False),
                                icon_path=icon_path,
                                template=config.get("template"),
                                document_type=config.get("document_type"),
                                path_globs=config.get("path_globs", []),
                                form=config.get("form"),
                                logic=config.get("logic"),
                                parser=config.get("parser"),
                                parser_entry=config.get("parser_entry"),
                                schema=config.get("schema"),
                                element_dir=element_dir,
                            )
                            profile.elements.append(element)
                    except Exception as e:
                        print(f"Failed to load element from {element_config_path}: {e}")

    def get_profiles(self):
        return self.profiles

def load_module_from_path(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
