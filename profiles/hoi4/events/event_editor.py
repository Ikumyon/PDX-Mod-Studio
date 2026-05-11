from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QListWidget, QPlainTextEdit, QRadioButton

from profiles.hoi4.script_parser import AssignmentNode, ObjectNode, Parser, ScalarNode


MODE_NAME = "Event Editor"


@dataclass
class ParsedEvent:
    key: str
    node: AssignmentNode
    properties: dict[str, list[AssignmentNode]] = field(default_factory=dict)

    @property
    def event_id(self) -> str:
        return scalar_text(first(self.properties.get("id", [])))

    def first(self, name: str) -> Optional[AssignmentNode]:
        return first(self.properties.get(name, []))


def setup(widget, file_path, content):
    controller = EventEditorController(widget, file_path, content)
    widget.profile_controller = controller
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    controller.bind()


class EventEditorController:
    def __init__(self, widget, file_path, content):
        self.widget = widget
        self.file_path = file_path
        self.widget.content = content
        self.events: list[ParsedEvent] = []
        self.selected_event_id = ""
        self.updating = False

    def bind(self):
        self.event_list = find(self.widget, QListWidget, "eventListWidget")
        self.event_id = find(self.widget, QLineEdit, "eventIdEdit")
        self.event_type = find(self.widget, QComboBox, "eventTypeCombo")
        self.title_key = find(self.widget, QLineEdit, "titleKeyEdit")
        self.desc_key = find(self.widget, QLineEdit, "descKeyEdit")
        self.picture = find(self.widget, QLineEdit, "pictureEdit")
        self.fire_only_once = find(self.widget, QCheckBox, "fireOnlyOnceCheck")
        self.hidden = find(self.widget, QCheckBox, "hiddenCheck")
        self.major = find(self.widget, QCheckBox, "majorCheck")
        self.triggered_only = find(self.widget, QRadioButton, "isTriggeredOnlyRadio")
        self.standard_trigger = find(self.widget, QRadioButton, "isStandardTriggerRadio")
        self.trigger = find(self.widget, QPlainTextEdit, "triggerEdit")
        self.mtth = find(self.widget, QPlainTextEdit, "mtthEdit")
        self.immediate = find(self.widget, QPlainTextEdit, "immediateEdit")

        if self.event_list:
            self.event_list.currentRowChanged.connect(self.on_event_selected)

        self.connect_scalar(self.event_id, "id")
        self.connect_scalar(self.title_key, "title")
        self.connect_scalar(self.desc_key, "desc")
        self.connect_scalar(self.picture, "picture")
        self.connect_bool(self.fire_only_once, "fire_only_once")
        self.connect_bool(self.hidden, "hidden")
        self.connect_bool(self.major, "major")
        self.connect_bool(self.triggered_only, "is_triggered_only")

        self.refresh()

    def set_content(self, content):
        self.widget.content = content
        self.refresh()

    def refresh(self):
        self.events = parse_events(self.widget.content)
        selected = self.selected_event_id
        self.updating = True
        try:
            if self.event_list:
                self.event_list.clear()
                for event in self.events:
                    label = event.event_id or f"{event.key}@{event.node.range.start.line}"
                    self.event_list.addItem(label)
                row = self.index_for_event_id(selected)
                self.event_list.setCurrentRow(row if row >= 0 else (0 if self.events else -1))
                self.load_event(self.current_event())
        finally:
            self.updating = False

    def on_event_selected(self, _row):
        if self.updating:
            return
        self.updating = True
        try:
            self.load_event(self.current_event())
        finally:
            self.updating = False

    def current_event(self) -> Optional[ParsedEvent]:
        if not self.event_list:
            return self.events[0] if self.events else None
        row = self.event_list.currentRow()
        if row < 0 or row >= len(self.events):
            return None
        return self.events[row]

    def load_event(self, event: Optional[ParsedEvent]):
        self.selected_event_id = event.event_id if event else ""
        set_line(self.event_id, prop_text(event, "id"))
        set_combo(self.event_type, event.key if event else "")
        set_line(self.title_key, prop_text(event, "title"))
        set_line(self.desc_key, prop_text(event, "desc"))
        set_line(self.picture, prop_text(event, "picture"))
        set_checked(self.fire_only_once, prop_bool(event, "fire_only_once"))
        set_checked(self.hidden, prop_bool(event, "hidden"))
        set_checked(self.major, prop_bool(event, "major"))
        triggered = prop_bool(event, "is_triggered_only")
        set_checked(self.triggered_only, triggered)
        set_checked(self.standard_trigger, not triggered)
        set_plain(self.trigger, block_text(self.widget.content, event, "trigger"))
        set_plain(self.mtth, block_text(self.widget.content, event, "mean_time_to_happen"))
        set_plain(self.immediate, block_text(self.widget.content, event, "immediate"))

    def connect_scalar(self, control, property_name):
        if control:
            control.editingFinished.connect(lambda name=property_name, edit=control: self.replace_property(name, edit.text()))

    def connect_bool(self, control, property_name):
        if control:
            control.toggled.connect(lambda checked, name=property_name: self.replace_property(name, "yes" if checked else "no"))

    def replace_property(self, property_name, replacement):
        if self.updating:
            return
        event = self.current_event()
        assignment = event.first(property_name) if event else None
        if not assignment:
            return
        value_range = assignment.value.range
        text = self.widget.content
        self.widget.content = text[:value_range.start_offset] + replacement + text[value_range.end_offset:]
        self.selected_event_id = replacement if property_name == "id" else event.event_id
        self.refresh()

    def index_for_event_id(self, event_id):
        if not event_id:
            return -1
        for index, event in enumerate(self.events):
            if event.event_id == event_id:
                return index
        return -1


def parse_events(content) -> list[ParsedEvent]:
    ast, _, _ = Parser(content).parse()
    events: list[ParsedEvent] = []
    for item in ast.items:
        if not isinstance(item, AssignmentNode):
            continue
        if item.key not in {"country_event", "news_event"}:
            continue
        parsed = ParsedEvent(item.key, item)
        if isinstance(item.value, ObjectNode):
            for child in item.value.items:
                if isinstance(child, AssignmentNode):
                    parsed.properties.setdefault(child.key, []).append(child)
        events.append(parsed)
    return events


def first(values):
    return values[0] if values else None


def find(widget, cls, name):
    return widget.findChild(cls, name)


def scalar_text(assignment: Optional[AssignmentNode]) -> str:
    if not assignment or not isinstance(assignment.value, ScalarNode):
        return ""
    return str(assignment.value.value)


def prop_text(event: Optional[ParsedEvent], name: str) -> str:
    return scalar_text(event.first(name)) if event else ""


def prop_bool(event: Optional[ParsedEvent], name: str) -> bool:
    assignment = event.first(name) if event else None
    if not assignment or not isinstance(assignment.value, ScalarNode):
        return False
    return bool(assignment.value.value)


def block_text(content: str, event: Optional[ParsedEvent], name: str) -> str:
    assignment = event.first(name) if event else None
    if not assignment:
        return ""
    return content[assignment.value.range.start_offset:assignment.value.range.end_offset]


def set_line(control, value):
    if control:
        control.setText(value)


def set_plain(control, value):
    if control:
        control.setPlainText(value)


def set_checked(control, value):
    if control:
        control.setChecked(bool(value))


def set_combo(control, value):
    if not control:
        return
    index = control.findText(value, Qt.MatchFlag.MatchExactly)
    if index >= 0:
        control.setCurrentIndex(index)
