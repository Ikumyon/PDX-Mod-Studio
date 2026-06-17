import os
import traceback
from PySide6.QtWidgets import QWidget, QStackedWidget, QLabel, QPushButton
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile
from core.i18n import tr

class RendererRegistry:
    def __init__(self):
        self._renderers = {}
        self._translators = []

    def register_renderer(self, renderer_id, renderer):
        self._renderers[renderer_id] = renderer
        self.load_renderer_translation(renderer)

    def get_renderer(self, renderer_id):
        return self._renderers.get(renderer_id)

    def load_renderer_translation(self, renderer):
        if hasattr(renderer, "get_translation_info"):
            info = renderer.get_translation_info()
            if info and isinstance(info, dict):
                directory = info.get("directory")
                filename = info.get("filename")
                if directory and filename:
                    from PySide6.QtCore import QTranslator, QLocale, QCoreApplication
                    
                    translator = QTranslator()
                    if translator.load(QLocale.system(), filename, "_", directory):
                        self._translators.append(translator)
                        app = QCoreApplication.instance()
                        if app:
                            app.installTranslator(translator)
                            print(f"Loaded renderer translation: {filename} from {directory}")
                    else:
                        print(f"Failed to load renderer translation: {filename} from {directory} for locale {QLocale.system().name()}")

    def install_translations(self, app):
        for translator in self._translators:
            app.installTranslator(translator)
            print("Installed registered renderer translator.")

renderer_registry = RendererRegistry()

class DashboardTabHostWidget(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.provider = None
        self.current_context = None
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # UIのロード
        loader = QUiLoader()
        ui_path = os.path.join(self.base_dir, "ui", "widgets", "DashboardTabHost.ui")
        ui_file = QFile(ui_path)
        if ui_file.open(QFile.ReadOnly):
            self.ui = loader.load(ui_file, self)
            ui_file.close()
            
            # レイアウトにロードしたウィジェットを追加
            layout = self.layout()
            if not layout:
                from PySide6.QtWidgets import QVBoxLayout
                layout = QVBoxLayout(self)
                layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.ui)
            
            # コントロールの取得
            self.dashboardStateStack = self.ui.findChild(QStackedWidget, "dashboardStateStack")
            self.dashboardLoadingPage = self.ui.findChild(QWidget, "dashboardLoadingPage")
            self.dashboardEmptyPage = self.ui.findChild(QWidget, "dashboardEmptyPage")
            self.dashboardErrorPage = self.ui.findChild(QWidget, "dashboardErrorPage")
            self.dashboardErrorMessageLabel = self.ui.findChild(QLabel, "dashboardErrorMessageLabel")
            self.dashboardRetryButton = self.ui.findChild(QPushButton, "dashboardRetryButton")
            self.dashboardContentPage = self.ui.findChild(QWidget, "dashboardContentPage")
            self.dashboardMountArea = self.ui.findChild(QWidget, "dashboardMountArea")
            
            # イベント接続
            if self.dashboardRetryButton:
                self.dashboardRetryButton.clicked.connect(self.refresh)
                
            self.showEmpty()
        else:
            print(f"Could not open DashboardTabHost.ui: {ui_path}")

    def showLoading(self):
        if self.dashboardStateStack:
            self.dashboardStateStack.setCurrentIndex(0)

    def showEmpty(self):
        if self.dashboardStateStack:
            self.dashboardStateStack.setCurrentIndex(1)

    def showError(self, message):
        if self.dashboardErrorMessageLabel:
            self.dashboardErrorMessageLabel.setText(message)
        if self.dashboardStateStack:
            self.dashboardStateStack.setCurrentIndex(2)

    def mountDashboard(self, widget):
        if not self.dashboardMountArea:
            return
            
        layout = self.dashboardMountArea.layout()
        if not layout:
            from PySide6.QtWidgets import QVBoxLayout
            layout = QVBoxLayout(self.dashboardMountArea)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            
        # 既存のウィジェットをクリア
        while layout.count() > 0:
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
                
        if widget:
            layout.addWidget(widget)
            
        if self.dashboardStateStack:
            self.dashboardStateStack.setCurrentIndex(3)

    def setDashboardProvider(self, provider):
        self.provider = provider

    def loadDashboard(self, project_context):
        self.current_context = project_context
        self.refresh()

    def refresh(self):
        # 現在のアクティブプロジェクト情報からプロバイダとコンテキストを再構築する
        if hasattr(self.parent_window, "project_tree") and self.parent_window.project_tree:
            project_tree = self.parent_window.project_tree
            active_plugin = getattr(project_tree, "active_plugin", None)
            if active_plugin:
                class PluginDashboardProvider:
                    def __init__(self, plugin):
                        self.plugin = plugin
                    def createDashboard(self, context):
                        res = self.plugin.call_named_hook("dashboard.create", {"context": context})
                        if not res:
                            provider_obj = self.plugin.call_named_hook("dashboard.provider", {"context": context})
                            if provider_obj and hasattr(provider_obj, "createDashboard"):
                                res = provider_obj.createDashboard(context)
                        return res
                self.setDashboardProvider(PluginDashboardProvider(active_plugin))
            else:
                self.setDashboardProvider(None)
                
            project_path = getattr(project_tree, "current_project_path", None)
            if project_path:
                self.current_context = {"project_path": project_path}
            else:
                self.current_context = None

        if not self.provider or not self.current_context:
            self.showEmpty()
            return
            
        self.showLoading()
        
        try:
            result = self.provider.createDashboard(self.current_context)
            if not result:
                self.showEmpty()
                return
                
            result_type = getattr(result, "type", None)
            if not result_type and isinstance(result, dict):
                result_type = result.get("type")
                
            if result_type == "widget":
                payload = getattr(result, "payload", None)
                if not payload and isinstance(result, dict):
                    payload = result.get("payload")
                self.mountDashboard(payload)
                
            elif result_type == "text":
                renderer_id = getattr(result, "renderer_id", None)
                payload = getattr(result, "payload", None)
                if isinstance(result, dict):
                    renderer_id = result.get("renderer_id")
                    payload = result.get("payload")
                    
                self._render_text_dashboard(renderer_id, payload)
            else:
                self.showError(tr("dashboard.error.unsupported_type: {type}").format(type=result_type))
                
        except Exception as e:
            traceback.print_exc()
            self.showError(tr("dashboard.error.load_failed: {error}").format(error=str(e)))

    def _render_text_dashboard(self, renderer_id, payload):
        if not renderer_id:
            self.showError(tr("dashboard.error.renderer_not_specified"))
            return
            
        renderer = renderer_registry.get_renderer(renderer_id)
        if not renderer:
            msg = tr("dashboard.error.renderer_not_found: {renderer_id}").format(renderer_id=renderer_id)
            self.showError(msg)
            return
            
        try:
            widget = renderer.render(payload, self.current_context)
            self.mountDashboard(widget)
        except Exception as e:
            traceback.print_exc()
            self.showError(tr("dashboard.error.render_failed: {error}").format(error=str(e)))
