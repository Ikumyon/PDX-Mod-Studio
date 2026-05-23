import ast
import os
import sys
import types

from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader
from core.i18n import tr


class EditorDefinition:
    def __init__(self, editor_id, name, py_path=None, ui_path=None, is_builtin=False):
        self.editor_id = editor_id
        self.name = name
        self.py_path = py_path
        self.ui_path = ui_path
        self.is_builtin = is_builtin



class EditorRegistry:
    BUILTIN_TEXT_EDITOR_ID = "core.plain_text"

    def __init__(self):
        self.text_editor_id = self.BUILTIN_TEXT_EDITOR_ID
        self.editors = {
            self.text_editor_id: EditorDefinition(
                self.text_editor_id,
                "テキストエディタ",
                is_builtin=True,
            )
        }

    def normalize_editor_id(self, editor_id):
        if not editor_id:
            return self.text_editor_id
        return editor_id

    def is_text_editor(self, editor_id):
        return self.normalize_editor_id(editor_id) == self.text_editor_id

    def get_editors_for_element(self, element):
        editor = self.register_element(element)
        return [editor] if editor else []

    def register_plugin(self, plugin):
        for element in getattr(plugin, "elements", []):
            self.register_element(element)

    def get_editor(self, editor_id):
        editor_id = self.normalize_editor_id(editor_id)
        return self.editors.get(editor_id)

    def register_element(self, element):
        if not getattr(element, "form", None) or not getattr(element, "logic", None):
            return None

        element_dir = getattr(element, "element_dir", None)
        if not element_dir:
            return None

        ui_path = os.path.join(element_dir, element.form)
        py_path = os.path.join(element_dir, element.logic)
        if not os.path.exists(ui_path) or not os.path.exists(py_path):
            return None

        editor_id = element.raw.get("editor_id")
        if not editor_id:
            return None

        editor_id = self.normalize_editor_id(editor_id)
        if editor_id not in self.editors:
            editor_name = self._extract_editor_name(py_path) or element.name
            self.editors[editor_id] = EditorDefinition(editor_id, editor_name, py_path, ui_path)
        return self.editors[editor_id]

    def _extract_editor_name(self, py_path):

        try:
            with open(py_path, "r", encoding="utf-8") as handle:
                module = ast.parse(handle.read(), filename=py_path)
            for node in module.body:
                if not isinstance(node, ast.Assign):
                    continue
                if not any(isinstance(target, ast.Name) and target.id in ("MODE_NAME", "EDITOR_NAME") for target in node.targets):
                    continue
                value = ast.literal_eval(node.value)
                return value if isinstance(value, str) else None
        except Exception as error:
            print(f"Failed to extract EDITOR_NAME from {py_path}: {error}")

            return None
        return None

    def _logic_module_name(self, editor_id):
        safe_id = "".join(ch if ch.isalnum() else "_" for ch in self.normalize_editor_id(editor_id))
        return f"pdx_editor_logic_{safe_id}"

    def create_editor_widget(self, editor_id, parent, file_path, content, tab_id=None):
        editor_id = self.normalize_editor_id(editor_id)
        if editor_id not in self.editors:
            return None

        editor = self.editors[editor_id]
        if editor.is_builtin:
            return None
        loader = QUiLoader()
        ui_file = QFile(editor.ui_path)

        if not ui_file.open(QFile.ReadOnly):
            return None

        widget = loader.load(ui_file, parent)
        ui_file.close()

        if not widget:
            return None

        try:
            with open(editor.py_path, "r", encoding="utf-8") as handle:
                py_code = handle.read()

            widget.file_path = file_path
            widget.editor_id = editor_id
            widget.content = content
            widget.tab_id = tab_id

            module_name = self._logic_module_name(editor_id)
            logic_module = types.ModuleType(module_name)
            logic_module.__file__ = editor.py_path
            logic_module.__package__ = ""
            namespace = logic_module.__dict__
            namespace.update({
                "widget": widget,
                "parent": parent,
                "file_path": file_path,
                "content": content,
                "__name__": module_name,
                "__file__": editor.py_path,
                "tr": tr,
            })
            sys.modules[module_name] = logic_module
            exec(py_code, namespace)

            setup = namespace.get("setup")
            if callable(setup):
                setup(widget, file_path, content)
        except Exception as error:
            print(f"Error binding logic for editor {editor_id}: {error}")

        return widget
