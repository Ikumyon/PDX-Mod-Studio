import ast
import os

from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader


class ModeDefinition:
    def __init__(self, mode_id, name, py_path, ui_path):
        self.mode_id = mode_id
        self.name = name
        self.py_path = py_path
        self.ui_path = ui_path


class ModeManager:
    def __init__(self):
        self.modes = {}
        self.script_mode_id = "script_mode"

    def get_modes_for_element(self, element):
        mode = self.register_element(element)
        return [mode] if mode else []

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

        mode_id = f"{element.id}:{element.document_type or element.path}:form"
        if mode_id not in self.modes:
            mode_name = self._extract_mode_name(py_path) or element.name
            self.modes[mode_id] = ModeDefinition(mode_id, mode_name, py_path, ui_path)
        return self.modes[mode_id]

    def _extract_mode_name(self, py_path):
        try:
            with open(py_path, "r", encoding="utf-8") as handle:
                module = ast.parse(handle.read(), filename=py_path)
            for node in module.body:
                if not isinstance(node, ast.Assign):
                    continue
                if not any(isinstance(target, ast.Name) and target.id == "MODE_NAME" for target in node.targets):
                    continue
                value = ast.literal_eval(node.value)
                return value if isinstance(value, str) else None
        except Exception as error:
            print(f"Failed to extract MODE_NAME from {py_path}: {error}")
            return None
        return None

    def create_mode_widget(self, mode_id, parent, file_path, content):
        if mode_id not in self.modes:
            return None

        mode = self.modes[mode_id]
        loader = QUiLoader()
        ui_file = QFile(mode.ui_path)
        if not ui_file.open(QFile.ReadOnly):
            return None

        widget = loader.load(ui_file, parent)
        ui_file.close()

        if not widget:
            return None

        try:
            with open(mode.py_path, "r", encoding="utf-8") as handle:
                py_code = handle.read()

            widget.file_path = file_path
            widget.mode_id = mode_id
            widget.content = content

            namespace = {
                "widget": widget,
                "parent": parent,
                "file_path": file_path,
                "content": content,
                "__file__": mode.py_path,
            }
            exec(py_code, namespace)

            setup = namespace.get("setup")
            if callable(setup):
                setup(widget, file_path, content)
        except Exception as error:
            print(f"Error binding logic for mode {mode_id}: {error}")

        return widget
