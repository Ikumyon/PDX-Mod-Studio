from PySide6.QtCore import QTimer

class DiagnosticsController:
    def __init__(self, parent_window, tab_controller):
        self.window = parent_window
        self.tab_controller = tab_controller

    def clear_language_diagnostics(self, widget):
        if not widget:
            return
        widget.diagnostic_count = 0
        if hasattr(widget, "clear_diagnostics"):
            widget.clear_diagnostics()
        self.tab_controller.update_tab_label(widget)

    def schedule_language_diagnostics(self, widget=None):
        if widget is None:
            widget = self.window.editorTabs.currentWidget() if self.window.editorTabs else None
        if not widget or not hasattr(widget, "set_diagnostics"):
            return

        timer = getattr(widget, "_language_diagnostic_timer", None)
        if timer is None:
            timer = QTimer(widget)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda w=widget: self.validate_language_diagnostics(w))
            widget._language_diagnostic_timer = timer
        timer.start(350)

    def schedule_all_language_diagnostics(self):
        if not self.window.editorTabs:
            return
        for index in range(self.window.editorTabs.count()):
            self.schedule_language_diagnostics(self.window.editorTabs.widget(index))

    def validate_language_diagnostics(self, widget):
        try:
            if widget:
                self.clear_language_diagnostics(widget)
        except (RuntimeError, ReferenceError):
            return
        except Exception:
            pass
