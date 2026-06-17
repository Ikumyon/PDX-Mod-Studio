from core import save_result as save_result_utils
from core.i18n import tr

class SaveController:
    def __init__(self, parent_window, tab_controller):
        self.window = parent_window
        self.tab_controller = tab_controller

    def show_save_result_message(self, result, default_timeout=5000):
        message = save_result_utils.save_result_message(result)
        if message:
            self.window.statusBar().showMessage(message, default_timeout)

    def clear_pending_save_plan(self, widget):
        widget.save_plan = None

    def finish_successful_save(self, widget, result=None):
        if result is None:
            result = {}
        if not isinstance(result, dict):
            result = save_result_utils.normalize_save_result(result)

        primary_path = result.get("primary_path", "")
        if not primary_path:
            primary_path = getattr(widget, "file_path", "")

        if primary_path:
            self.tab_controller.update_saved_widget_path(widget, primary_path)
        self.tab_controller.mark_tab_clean(widget)
        self.clear_pending_save_plan(widget)

    def finish_unsuccessful_save(self, widget):
        self.clear_pending_save_plan(widget)

    def save_active_tab(self, save_as=False):
        if not self.window.editorTabs:
            return False

        widget = self.window.editorTabs.currentWidget()
        if not widget:
            self.window.statusBar().showMessage(tr("dashboard.error.save_no_tab", "MainWindow"), 3000)
            return False

        handler_name = "on_save_as_triggered" if save_as else "on_save_triggered"
        handler = getattr(widget, handler_name, None)
        if not callable(handler):
            self.window.statusBar().showMessage(tr("dashboard.error.save_not_supported", "MainWindow"), 4000)
            return False

        try:
            plan_result = save_result_utils.normalize_save_result(handler())
        except Exception as error:
            self.window.statusBar().showMessage(
                tr("dashboard.error.save_failed: {error}", "MainWindow").format(error=error),
                5000,
            )
            return False

        if save_result_utils.is_save_cancelled(plan_result):
            self.finish_unsuccessful_save(widget)
            self.show_save_result_message(plan_result)
            return False

        if not save_result_utils.is_save_success(plan_result):
            self.finish_unsuccessful_save(widget)
            self.show_save_result_message(plan_result)
            return False

        save_plan = getattr(widget, "save_plan", None)
        if not save_plan:
            self.finish_successful_save(widget, plan_result)
            return True

        writer = getattr(widget, "on_write_save_plan", None)
        if not callable(writer):
            self.window.statusBar().showMessage(tr("dashboard.error.write_not_supported", "MainWindow"), 4000)
            return False

        try:
            write_result = save_result_utils.normalize_save_result(writer())
        except Exception as error:
            self.window.statusBar().showMessage(
                tr("dashboard.error.write_failed: {error}", "MainWindow").format(error=error),
                5000,
            )
            self.finish_unsuccessful_save(widget)
            return False

        if save_result_utils.is_save_success(write_result):
            self.finish_successful_save(widget, write_result)
            return True
        self.finish_unsuccessful_save(widget)
        self.show_save_result_message(write_result)
        return False
