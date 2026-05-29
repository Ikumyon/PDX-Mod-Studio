import os
import json
import zipfile
import tempfile
from PySide6.QtWidgets import QFileDialog, QMessageBox

PROJECT_TYPE_REFERENCE = "reference"
PROJECT_TYPE_EMBEDDED = "embedded"

def write_json_file(path, data):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)

def read_json_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)

class ProjectIOManager:
    def __init__(self, window, project_tree, base_dir, get_plugin_by_id, select_plugin, active_required_plugins, export_all_plugin_data, plugin_import_project_data):
        self.window = window
        self.project_tree = project_tree
        self.base_dir = base_dir
        self.get_plugin_by_id = get_plugin_by_id
        self.select_plugin = select_plugin
        self.active_required_plugins = active_required_plugins
        self.export_all_plugin_data = export_all_plugin_data
        self.plugin_import_project_data = plugin_import_project_data

    def normalise_project_type(self, project_type):
        if project_type == PROJECT_TYPE_REFERENCE:
            return PROJECT_TYPE_REFERENCE
        if project_type == PROJECT_TYPE_EMBEDDED:
            return PROJECT_TYPE_EMBEDDED
        return PROJECT_TYPE_REFERENCE

    def current_project_metadata(self, project_type):
        project_type = self.normalise_project_type(project_type)
        project_path = getattr(self.project_tree, "current_project_path", None)
        display_name = os.path.basename(os.path.normpath(project_path)) if project_path else "Untitled Project"
        metadata = {
            "schema_version": 1,
            "project_type": project_type,
            "required_plugins": self.active_required_plugins(),
            "display_name": display_name,
            "mod_root": "mod" if project_type == PROJECT_TYPE_EMBEDDED else project_path,
        }
        if project_type == PROJECT_TYPE_EMBEDDED:
            metadata["source_mod_root"] = getattr(self.window, "source_mod_root", None) or project_path
        return metadata

    def project_context(self, metadata, project_file, mod_root):
        return {
            "project_file": project_file,
            "project_type": self.normalise_project_type(metadata.get("project_type")),
            "mod_root": mod_root,
            "required_plugins": metadata.get("required_plugins", []),
            "metadata": metadata,
        }

    def ensure_project_path(self):
        project_path = getattr(self.project_tree, "current_project_path", None)
        if project_path and os.path.isdir(project_path):
            return project_path
        self.window.statusBar().showMessage("No project folder is open.", 5000)
        return None

    def project_save_path_dialog(self):
        start_dir = getattr(self.project_tree, "current_project_path", None) or self.base_dir
        path, selected_filter = QFileDialog.getSaveFileName(
            self.window,
            "プロジェクトを保存",
            start_dir,
            "参照型プロジェクト (*.pdxproj);;内包型プロジェクト (*.pdxpkg)",
        )
        if not path:
            return None
        if not path.lower().endswith((".pdxproj", ".pdxpkg")):
            path += ".pdxpkg" if "内包型" in selected_filter else ".pdxproj"
        return path

    def project_type_for_path(self, path):
        return PROJECT_TYPE_EMBEDDED if path.lower().endswith(".pdxpkg") else PROJECT_TYPE_REFERENCE

    def save_reference_project(self, path):
        mod_root = self.ensure_project_path()
        if not mod_root:
            return False
        metadata = self.current_project_metadata(PROJECT_TYPE_REFERENCE)
        context = self.project_context(metadata, path, mod_root)
        metadata["plugin_data"] = self.export_all_plugin_data(context)
        write_json_file(path, metadata)
        self.window.current_project_file = path
        self.window.current_project_type = PROJECT_TYPE_REFERENCE
        self.window.statusBar().showMessage(f"Project saved: {path}", 3000)
        return True

    def add_directory_to_zip(self, archive, source_dir, archive_root):
        for root, _, files in os.walk(source_dir):
            for filename in files:
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, source_dir)
                archive_path = os.path.join(archive_root, rel_path).replace("\\", "/")
                archive.write(full_path, archive_path)

    def save_embedded_project(self, path):
        mod_root = self.ensure_project_path()
        if not mod_root:
            return False
        metadata = self.current_project_metadata(PROJECT_TYPE_EMBEDDED)
        context = self.project_context(metadata, path, mod_root)
        plugin_data = self.export_all_plugin_data(context)
        temp_fd, temp_path = tempfile.mkstemp(suffix=".pdxpkg")
        os.close(temp_fd)
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project.json", json.dumps(metadata, indent=4, ensure_ascii=False))
            self.add_directory_to_zip(archive, mod_root, "mod")
            for plugin_id, data in plugin_data.items():
                for data_key, payload in (data or {}).items():
                    archive.writestr(
                        f"plugin_data/{plugin_id}/{data_key}.json",
                        json.dumps(payload, indent=4, ensure_ascii=False),
                    )
        os.replace(temp_path, path)
        self.window.current_project_file = path
        self.window.current_project_type = PROJECT_TYPE_EMBEDDED
        self.window.statusBar().showMessage(f"Project package saved: {path}", 3000)
        return True

    def save_project_to(self, path):
        try:
            if self.project_type_for_path(path) == PROJECT_TYPE_EMBEDDED:
                return self.save_embedded_project(path)
            return self.save_reference_project(path)
        except Exception as error:
            self.window.statusBar().showMessage(f"Failed to save project: {error}", 5000)
            return False

    def save_project(self):
        path = getattr(self.window, "current_project_file", None)
        if not path:
            return self.save_project_as()
        return self.save_project_to(path)

    def save_project_as(self):
        path = self.project_save_path_dialog()
        if not path:
            return False
        return self.save_project_to(path)

    def open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "プロジェクトを開く",
            self.base_dir,
            "PDX Mod Studio プロジェクト (*.pdxproj *.pdxpkg)",
        )
        if path:
            self.open_project_file(path)

    def apply_required_plugins(self, metadata):
        missing = []
        for plugin_id in metadata.get("required_plugins", []):
            plugin = self.get_plugin_by_id(plugin_id)
            if plugin:
                self.select_plugin(plugin)
            else:
                missing.append(plugin_id)
        if missing:
            self.window.statusBar().showMessage(f"Missing required plugins: {', '.join(missing)}", 7000)

    def import_all_plugin_data(self, metadata, project_file, mod_root, plugin_data):
        context = self.project_context(metadata, project_file, mod_root)
        for plugin_id, data in (plugin_data or {}).items():
            plugin = self.get_plugin_by_id(plugin_id)
            if plugin:
                self.plugin_import_project_data(plugin, context, data)

    def open_reference_project(self, path):
        metadata = read_json_file(path)
        mod_root = metadata.get("mod_root")
        if not mod_root or not os.path.isdir(mod_root):
            self.window.statusBar().showMessage("Project mod_root does not exist.", 7000)
            return False
        self.apply_required_plugins(metadata)
        self.project_tree.load_project(mod_root)
        self.import_all_plugin_data(metadata, path, mod_root, metadata.get("plugin_data", {}))
        self.window.current_project_file = path
        self.window.current_project_type = PROJECT_TYPE_REFERENCE
        self.window.statusBar().showMessage(f"Project opened: {path}", 3000)
        return True

    def read_zip_json(self, archive, name):
        with archive.open(name) as handle:
            return json.loads(handle.read().decode("utf-8"))

    def open_embedded_project(self, path):
        workspace = tempfile.mkdtemp(prefix="pdx_mod_studio_")
        with zipfile.ZipFile(path, "r") as archive:
            metadata = self.read_zip_json(archive, "project.json")
            archive.extractall(workspace)
        mod_root = os.path.join(workspace, metadata.get("mod_root", "mod"))
        if not os.path.isdir(mod_root):
            self.window.statusBar().showMessage("Project package does not contain mod/.", 7000)
            return False
        self.apply_required_plugins(metadata)
        self.project_tree.load_project(mod_root)
        plugin_data = {}
        plugin_data_root = os.path.join(workspace, "plugin_data")
        for plugin_id in metadata.get("required_plugins", []):
            plugin_dir = os.path.join(plugin_data_root, plugin_id)
            plugin_data[plugin_id] = {}
            if os.path.isdir(plugin_dir):
                for filename in os.listdir(plugin_dir):
                    if filename.endswith(".json"):
                        data_key = os.path.splitext(filename)[0]
                        plugin_data[plugin_id][data_key] = read_json_file(os.path.join(plugin_dir, filename))
        self.import_all_plugin_data(metadata, path, mod_root, plugin_data)
        self.window.current_project_file = path
        self.window.current_project_type = PROJECT_TYPE_EMBEDDED
        self.window.embedded_project_workspace = workspace
        self.window.source_mod_root = metadata.get("source_mod_root")
        self.window.statusBar().showMessage(f"Project package opened: {path}", 3000)
        return True

    def open_project_file(self, path):
        try:
            if path.lower().endswith(".pdxpkg"):
                return self.open_embedded_project(path)
            return self.open_reference_project(path)
        except Exception as error:
            self.window.statusBar().showMessage(f"Failed to open project: {error}", 7000)
            return False
