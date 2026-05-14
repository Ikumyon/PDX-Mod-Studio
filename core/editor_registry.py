import ast
import os

from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader


class EditorDefinition:
    def __init__(self, editor_id, name, py_path, ui_path):
        self.editor_id = editor_id
        self.name = name
        self.py_path = py_path
        self.ui_path = ui_path



class EditorRegistry:
    def __init__(self):
        self.editors = {}
        self.text_editor_id = "text"

    def get_editors_for_element(self, element):
        editor = self.register_element(element)
        return [editor] if editor else []


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

        editor_id = f"{element.id}:{element.document_type or element.path}:form"
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

    def create_editor_widget(self, editor_id, parent, file_path, content):
        if editor_id not in self.editors:
            return None

        editor = self.editors[editor_id]
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


            namespace = {
                "widget": widget,
                "parent": parent,
                "file_path": file_path,
                "content": content,
                "__file__": editor.py_path,
            }
            exec(py_code, namespace)

            setup = namespace.get("setup")
            if callable(setup):
                setup(widget, file_path, content)
        except Exception as error:
            print(f"Error binding logic for editor {editor_id}: {error}")

        return widget

