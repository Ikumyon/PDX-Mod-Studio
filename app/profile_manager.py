import os
import json
import importlib.util

from core.engine.profile import DocumentTypeRule, ProfileDefinition
from core.engine.runtime import Document
from core.engine.model import Diagnostic, SourcePosition, SourceRange

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


def load_profile_definition(profile):
    """Build an engine profile from an already discovered app profile."""
    data = dict(profile.raw)
    inline_document_types = [
        DocumentTypeRule(
            id=item["id"],
            path_globs=item.get("path_globs", []),
            extensions=item.get("extensions", []),
        )
        for item in data.get("document_types", [])
    ]
    config_document_types = document_types_from_elements(profile.elements)
    element_definitions = definitions_from_elements(profile.elements)
    data["document_types"] = [
        {
            "id": document_type.id,
            "path_globs": document_type.path_globs,
            "extensions": document_type.extensions,
        }
        for document_type in dedupe_document_types(inline_document_types + config_document_types)
    ]
    data["schemas"] = {
        **data.get("schemas", {}),
        **element_definitions["schemas"],
    }
    data["entity_rules"] = data.get("entity_rules", []) + element_definitions["entity_rules"]
    data["relations"] = data.get("relations", []) + element_definitions["relations"]
    return ProfileDefinition.from_dict(data)


def create_profile_adapter(profile):
    profile_definition = load_profile_definition(profile)
    parsers = parsers_from_elements(profile.elements, profile_definition)
    return ElementProfileAdapter(profile_definition, parsers)


class ElementProfileAdapter:
    def __init__(self, profile_definition, parsers):
        self.profile = profile_definition
        self.parsers = parsers

    def parse_document(self, path: str, text: str, project_root: str = "") -> Document:
        relative_path = os.path.relpath(path, project_root) if project_root else path
        document_type = self.profile.classify_document(relative_path)
        parser = self.parsers.get(document_type)
        if not parser:
            return unparsed_document(path, relative_path, text, document_type)
        return parser.parse_document(path, text, project_root)


def parsers_from_elements(elements, profile_definition):
    parsers = {}
    for element in elements:
        if not element.document_type or not element.parser or not element.element_dir:
            continue

        parser_path = os.path.join(element.element_dir, element.parser)
        module = load_module_from_path(f"profile_{element.id}_parser", parser_path)
        entry_name = element.parser_entry or "PARSER_CLASS"
        parser_class = getattr(module, entry_name)
        parsers[element.document_type] = parser_class(profile_definition)
    return parsers


def load_module_from_path(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unparsed_document(path, relative_path, text, document_type):
    position = SourcePosition(0, 1, 1)
    source_range = SourceRange(position, position)
    diagnostic = Diagnostic(
        severity="info",
        message=f"No parser registered for document type '{document_type}'",
        range=source_range,
        code="parser-not-registered",
        source="profile-manager",
    )
    normalized_relative_path = relative_path.replace("\\", "/")
    return Document(
        id=normalized_relative_path,
        path=path,
        relative_path=normalized_relative_path,
        text=text,
        document_type=document_type,
        ast=None,
        tokens=[],
        diagnostics=[diagnostic],
        newline="\r\n" if "\r\n" in text else "\n",
    )


def definitions_from_elements(elements):
    definitions = {
        "schemas": {},
        "entity_rules": [],
        "relations": [],
    }
    for element in elements:
        if not element.schema or not element.element_dir:
            continue

        schema_path = os.path.join(element.element_dir, element.schema)
        with open(schema_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        if "schemas" in data:
            definitions["schemas"].update(data["schemas"])
        elif "id" in data:
            definitions["schemas"][data["id"]] = data
        definitions["entity_rules"].extend(data.get("entity_rules", []))
        definitions["relations"].extend(data.get("relations", []))
    return definitions


def document_types_from_elements(elements):
    document_types = []
    for element in elements:
        if not element.document_type:
            continue

        extensions = [element.extension] if element.extension else []
        path_globs = element.path_globs or default_path_globs(element.path, extensions)
        document_types.append(
            DocumentTypeRule(
                id=element.document_type,
                path_globs=path_globs,
                extensions=extensions,
            )
        )
    return document_types


def default_path_globs(path, extensions):
    normalized = path.replace("\\", "/").strip("/")
    if not normalized:
        return []
    suffixes = extensions or [""]
    patterns = []
    for suffix in suffixes:
        patterns.append(f"{normalized}/*{suffix}")
        patterns.append(f"{normalized}/**/*{suffix}")
    return patterns


def dedupe_document_types(document_types):
    merged = {}
    for document_type in document_types:
        if document_type.id not in merged:
            merged[document_type.id] = DocumentTypeRule(
                id=document_type.id,
                path_globs=list(document_type.path_globs),
                extensions=list(document_type.extensions),
            )
            continue

        existing = merged[document_type.id]
        for pattern in document_type.path_globs:
            if pattern not in existing.path_globs:
                existing.path_globs.append(pattern)
        for extension in document_type.extensions:
            if extension not in existing.extensions:
                existing.extensions.append(extension)
    return list(merged.values())
