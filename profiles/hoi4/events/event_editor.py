from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import Qt, QFile
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QListWidget, QPlainTextEdit, QRadioButton, QPushButton, QSpinBox
from PySide6.QtUiTools import QUiLoader

from profiles.hoi4.script_parser import AssignmentNode, ObjectNode, Parser, ScalarNode, DocumentAst


from profiles.hoi4.events.event_parser import EventParser, ParsedEvent


MODE_NAME = "Event Editor"


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
        # パーサーの初期化 (ダミーのプロファイルオブジェクトを渡す)
        self.parser = EventParser(profile=object())

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
        self.fire_for_sender = find(self.widget, QCheckBox, "fireForSenderCheck")
        self.timeout_days = find(self.widget, QSpinBox, "timeoutSpin")
        self.triggered_only = find(self.widget, QRadioButton, "isTriggeredOnlyRadio")
        self.standard_trigger = find(self.widget, QRadioButton, "isStandardTriggerRadio")
        self.trigger = find(self.widget, QPlainTextEdit, "triggerEdit")
        self.mtth = find(self.widget, QPlainTextEdit, "mtthEdit")
        self.immediate = find(self.widget, QPlainTextEdit, "immediateEdit")
        self.after = find(self.widget, QPlainTextEdit, "afterEdit")
        self.doc_prop_widgets = {}

        # 選択肢関連
        self.options_layout = self.widget.findChild(object, "optionsLayout")
        self.add_option_btn = find(self.widget, QPushButton, "addOptionButton")
        if self.add_option_btn:
            self.add_option_btn.clicked.connect(self.add_new_option)

        # ドキュメントプロパティのバインド
        for prop_key, prop_def in self.parser.schema.get("document_properties", {}).items():
            widget_name = prop_def.get("ui_widget")
            if widget_name:
                widget = find(self.widget, QLineEdit, widget_name)
                if widget:
                    self.doc_prop_widgets[prop_key] = widget
                    widget.editingFinished.connect(lambda k=prop_key: self.on_doc_prop_edited(k))

        if self.event_list:
            self.event_list.currentRowChanged.connect(self.on_event_selected)

        self.connect_scalar(self.event_id, "id")
        self.connect_scalar(self.title_key, "title")
        self.connect_scalar(self.desc_key, "desc")
        self.connect_scalar(self.picture, "picture")
        self.connect_bool(self.fire_only_once, "fire_only_once")
        self.connect_bool(self.hidden, "hidden")
        self.connect_bool(self.major, "major")
        self.connect_bool(self.fire_for_sender, "fire_for_sender")
        if self.timeout_days:
            self.timeout_days.valueChanged.connect(lambda val: self.replace_property("timeout_days", str(val) if val > 0 else ""))
        
        if self.triggered_only:
            self.triggered_only.toggled.connect(self.on_trigger_type_changed)
        if self.standard_trigger:
            self.standard_trigger.toggled.connect(self.on_trigger_type_changed)
        
        # トップレベルのテキストエディタの接続
        if self.trigger:
            self.trigger.focusOutEvent = lambda event: self.on_top_text_focus_out("trigger", self.trigger, event)
        if self.mtth:
            self.mtth.focusOutEvent = lambda event: self.on_top_text_focus_out("mean_time_to_happen", self.mtth, event)
        if self.immediate:
            self.immediate.focusOutEvent = lambda event: self.on_top_text_focus_out("immediate", self.immediate, event)
        if self.after:
            self.after.focusOutEvent = lambda event: self.on_top_text_focus_out("after", self.after, event)

        self.refresh()

    def on_top_text_focus_out(self, key, edit, event):
        QPlainTextEdit.focusOutEvent(edit, event)
        self.replace_property(key, edit.toPlainText())

    def set_content(self, content):
        self.widget.content = content
        self.refresh()

    def refresh(self):
        # EventParser に解析を依頼
        doc = self.parser.parse_document(self.file_path, self.widget.content)
        self.events = getattr(doc, "events", [])
        
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
            
            for prop_key, widget in self.doc_prop_widgets.items():
                val = getattr(doc, "properties", {}).get(prop_key, "")
                widget.setText(val)
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
        set_checked(self.fire_for_sender, prop_bool(event, "fire_for_sender"))
        if self.timeout_days:
            self.timeout_days.setValue(int(prop_text(event, "timeout_days") or 0))
        triggered = prop_bool(event, "is_triggered_only")
        set_checked(self.triggered_only, triggered)
        set_checked(self.standard_trigger, not triggered)
        set_plain(self.trigger, block_text(self.widget.content, event.node if event else None, "trigger"))
        set_plain(self.mtth, block_text(self.widget.content, event.node if event else None, "mean_time_to_happen"))
        set_plain(self.immediate, block_text(self.widget.content, event.node if event else None, "immediate"))
        set_plain(self.after, block_text(self.widget.content, event.node if event else None, "after"))

        self.update_trigger_ui()
        self.refresh_options(event)

    def refresh_options(self, event: Optional[ParsedEvent]):
        if not self.options_layout:
            return

        # 既存のウィジェットを削除 (addOptionButton以外)
        while self.options_layout.count() > 1:
            item = self.options_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not event:
            return

        loader = QUiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "event_option_node.ui")
        
        # AI選択確率の集計
        option_factors = []
        for opt in event.options:
            factor = 1
            properties = {}
            if isinstance(opt.value, ObjectNode):
                for item in opt.value.items:
                    if isinstance(item, AssignmentNode):
                        properties.setdefault(item.key, []).append(item)
            
            ai_chance_node = first(properties.get("ai_chance", []))
            if ai_chance_node and isinstance(ai_chance_node.value, ObjectNode):
                factor_node = first([item for item in ai_chance_node.value.items if isinstance(item, AssignmentNode) and item.key == "factor"])
                if factor_node and isinstance(factor_node.value, ScalarNode):
                    try: factor = float(factor_node.value.value)
                    except: pass
            option_factors.append(factor)
        
        total_factor = sum(option_factors)

        for i, option in enumerate(event.options):
            ui_file = QFile(ui_path)
            if not ui_file.open(QFile.ReadOnly):
                continue
            
            option_widget = loader.load(ui_file)
            ui_file.close()
            
            if not option_widget:
                continue

            # タイトルの設定
            title_label = find(option_widget, object, "optionTitle")
            if title_label:
                prob = (option_factors[i] / total_factor * 100) if total_factor > 0 else 0
                title_label.setText(f"選択肢 {i+1} (AI確率: {prob:.1f}%)")

            # データのパース
            properties = {}
            if isinstance(option.value, ObjectNode):
                for item in option.value.items:
                    if isinstance(item, AssignmentNode):
                        properties.setdefault(item.key, []).append(item)

            # 各フィールドへの値セット
            name_edit = find(option_widget, QLineEdit, "nameKeyEdit")
            set_line(name_edit, scalar_text(first(properties.get("name", []))))
            if name_edit:
                name_edit.editingFinished.connect(lambda idx=i, edit=name_edit: self.update_option_property(idx, "name", edit.text()))

            ai_spin = find(option_widget, QSpinBox, "aiSpin")
            ai_chance_node = first(properties.get("ai_chance", []))
            ai_val = -1
            if ai_chance_node and isinstance(ai_chance_node.value, ObjectNode):
                factor_node = first([item for item in ai_chance_node.value.items if isinstance(item, AssignmentNode) and item.key == "factor"])
                if factor_node and isinstance(factor_node.value, ScalarNode):
                    ai_val = int(factor_node.value.value)
            if ai_spin:
                ai_spin.setValue(ai_val)
                ai_spin.valueChanged.connect(lambda val, idx=i: self.update_option_ai_chance(idx, val))

            effect_edit = find(option_widget, QPlainTextEdit, "effectEdit")
            trigger_edit = find(option_widget, QPlainTextEdit, "triggerEdit")
            hidden_effect_edit = find(option_widget, QPlainTextEdit, "hiddenEffectEdit")

            set_plain(trigger_edit, block_text(self.widget.content, option, "trigger"))
            set_plain(hidden_effect_edit, block_text(self.widget.content, option, "hidden_effect"))

            if effect_edit and isinstance(option.value, ObjectNode):
                items = [item for item in option.value.items if isinstance(item, AssignmentNode) and item.key not in {"name", "ai_chance", "trigger", "hidden_effect", "original_sender", "picture", "tooltip", "show_sound"}]
                effect_texts = [self.widget.content[item.range.start_offset:item.range.end_offset] for item in items]
                set_plain(effect_edit, "\n".join(effect_texts))

            # 変更時の保存処理の接続 (簡易化のため lambda でラップ)
            if trigger_edit:
                trigger_edit.focusInEvent = lambda event, idx=i, edit=trigger_edit: QPlainTextEdit.focusInEvent(edit, event)
                trigger_edit.focusOutEvent = lambda event, idx=i, edit=trigger_edit: self.on_option_text_focus_out(idx, "trigger", edit, event)
            if hidden_effect_edit:
                hidden_effect_edit.focusOutEvent = lambda event, idx=i, edit=hidden_effect_edit: self.on_option_text_focus_out(idx, "hidden_effect", edit, event)
            if effect_edit:
                effect_edit.focusOutEvent = lambda event, idx=i, edit=effect_edit: self.on_option_effects_focus_out(idx, edit, event)

            remove_btn = find(option_widget, object, "removeButton")
            if remove_btn:
                remove_btn.clicked.connect(lambda idx=i: self.remove_option(idx))

            # レイアウトに追加 (addOptionButton の上に挿入)
            self.options_layout.insertWidget(self.options_layout.count() - 1, option_widget)

    def on_option_text_focus_out(self, idx, key, edit, event):
        QPlainTextEdit.focusOutEvent(edit, event)
        self.update_option_property(idx, key, edit.toPlainText())

    def on_option_effects_focus_out(self, idx, edit, event):
        QPlainTextEdit.focusOutEvent(edit, event)
        self.update_option_effects(idx, edit.toPlainText())

    def update_option_effects(self, option_index, new_effects_text):
        if self.updating: return
        event = self.current_event()
        if not event or option_index >= len(event.options): return
        option = event.options[option_index]
        text = self.widget.content
        
        items = []
        if isinstance(option.value, ObjectNode):
            items = [item for item in option.value.items if isinstance(item, AssignmentNode) and item.key not in {"name", "ai_chance", "trigger", "hidden_effect", "original_sender", "picture", "tooltip", "show_sound"}]
        
        if items:
            start = items[0].range.start_offset
            end = items[-1].range.end_offset
            self.widget.content = text[:start] + new_effects_text + text[end:]
        else:
            # trigger の後付近に挿入
            self.update_option_property(option_index, "_effects", new_effects_text)
            return # update_option_property が refresh を呼ぶ
        self.refresh()

    def add_new_option(self):
        event = self.current_event()
        if not event:
            return
        
        text = self.widget.content
        close_brace_offset = event.node.range.end_offset - 1
        
        new_option_text = '\n\toption = {\n\t\tname = ""\n\t}'
        self.widget.content = text[:close_brace_offset] + new_option_text + text[close_brace_offset:]
        self.refresh()

    def remove_option(self, index):
        event = self.current_event()
        if not event or index >= len(event.options):
            return
        
        option = event.options[index]
        text = self.widget.content
        self.widget.content = text[:option.range.start_offset] + text[option.range.end_offset:]
        self.refresh()

    def update_option_property(self, option_index, key, value):
        if self.updating:
            return
        event = self.current_event()
        if not event or option_index >= len(event.options):
            return
        
        option = event.options[option_index]
        text = self.widget.content

        # 既存のプロパティを検索
        target = None
        if isinstance(option.value, ObjectNode):
            for item in option.value.items:
                if isinstance(item, AssignmentNode) and item.key == key:
                    target = item
                    break
        
        if not value or (key == "ai_chance" and value == "-1"):
            if target:
                start = target.range.start_offset
                end = target.range.end_offset
                if start > 0 and text[start-1] == "\n": start -= 1
                self.widget.content = text[:start] + text[end:]
                self.refresh()
            return

        is_object = key in {"trigger", "hidden_effect", "ai_chance"}
        if key == "ai_chance":
            formatted_value = f"{{\n\t\t\tfactor = {value}\n\t\t}}"
        elif is_object:
            # 各行にインデントを追加
            indented = "\n".join(["\t\t\t" + line if line.strip() else line for line in value.splitlines()])
            formatted_value = f"{{\n{indented}\n\t\t}}"
        else:
            formatted_value = f'"{value}"'

        if target:
            val_range = target.value.range
            self.widget.content = text[:val_range.start_offset] + formatted_value + text[val_range.end_offset:]
        else:
            # 順序に従って挿入場所を特定
            order = ["name", "ai_chance", "trigger", "hidden_effect"]
            try:
                target_idx = order.index(key)
            except ValueError:
                target_idx = 2.5 # trigger と hidden_effect の間（一般エフェクト）

            insertion_offset = option.range.end_offset - 1
            insert_before_node = None
            if isinstance(option.value, ObjectNode):
                for item in option.value.items:
                    if isinstance(item, AssignmentNode):
                        try:
                            idx = order.index(item.key)
                        except ValueError:
                            idx = 2.5
                        if idx > target_idx:
                            if insert_before_node is None or item.range.start_offset < insertion_offset:
                                insertion_offset = item.range.start_offset
                                insert_before_node = item
            
            if insert_before_node:
                new_prop = f"{key} = {formatted_value}\n\t\t"
            else:
                new_prop = f"\n\t\t{key} = {formatted_value}\n\t"
            
            self.widget.content = text[:insertion_offset] + new_prop + text[insertion_offset:]
            
        self.refresh()

    def update_option_ai_chance(self, option_index, value):
        self.update_option_property(option_index, "ai_chance", str(value))

    def on_trigger_type_changed(self, checked):
        if self.updating or not checked:
            return
        
        is_triggered_only = self.triggered_only.isChecked()
        
        if is_triggered_only:
            # 自然発生しない場合、is_triggered_only = yes を設定し、他を削除
            self.replace_property("is_triggered_only", "yes")
            self.replace_property("trigger", "")
            self.replace_property("mean_time_to_happen", "")
        else:
            # 通常発生の場合、is_triggered_only を削除
            self.replace_property("is_triggered_only", "")
            
        self.update_trigger_ui()

    def update_trigger_ui(self):
        is_triggered_only = self.triggered_only.isChecked()
        if self.trigger:
            self.trigger.setEnabled(not is_triggered_only)
        if self.mtth:
            self.mtth.setEnabled(not is_triggered_only)

    def on_doc_prop_edited(self, prop_key):
        if self.updating: return
        widget = self.doc_prop_widgets.get(prop_key)
        if widget:
            self.replace_top_level_property(prop_key, widget.text())


    def replace_top_level_property(self, property_name, replacement):
        if self.updating: return
        doc = self.parser.parse_document(self.file_path, self.widget.content)
        text = self.widget.content
        
        target = None
        for item in doc.ast.items:
            if isinstance(item, AssignmentNode) and item.key == property_name:
                target = item
                break
        
        if not replacement:
            if target:
                start = target.range.start_offset
                end = target.range.end_offset
                if start > 0 and text[start-1] == "\n": start -= 1
                self.widget.content = text[:start] + text[end:]
                self.refresh()
            return

        if target:
            val_range = target.value.range
            self.widget.content = text[:val_range.start_offset] + replacement + text[val_range.end_offset:]
        else:
            new_prop = f"{property_name} = {replacement}\n\n"
            self.widget.content = new_prop + text
            
        self.refresh()

    def connect_scalar(self, control, property_name):
        if control:
            control.editingFinished.connect(lambda name=property_name, edit=control: self.replace_property(name, edit.text()))

    def connect_bool(self, control, property_name):
        if control:
            control.toggled.connect(lambda checked, name=property_name: self.replace_property(name, "yes" if checked else ""))

    def replace_property(self, property_name, replacement):
        if self.updating:
            return
        event = self.current_event()
        if not event:
            return
            
        assignment = event.first(property_name)
        text = self.widget.content

        if not replacement:
            # 削除
            if assignment:
                start = assignment.range.start_offset
                end = assignment.range.end_offset
                if start > 0 and text[start-1] == "\n": start -= 1
                self.widget.content = text[:start] + text[end:]
                self.refresh()
            return

        # 更新または追加
        is_object = property_name in {"trigger", "mean_time_to_happen", "immediate", "after"}
        if is_object:
            # 各行にインデントを追加
            indented = "\n".join(["\t\t" + line if line.strip() else line for line in replacement.splitlines()])
            formatted_val = f"{{\n{indented}\n\t}}"
        else:
            formatted_val = replacement

        if assignment:
            # 更新
            value_range = assignment.value.range
            self.widget.content = text[:value_range.start_offset] + formatted_val + text[value_range.end_offset:]
        else:
            # プロパティの論理的な順序定義
            order = [
                "id", "title", "desc", "picture",
                "fire_only_once", "hidden", "major", "fire_for_sender", "timeout_days",
                "is_triggered_only", "trigger", "mean_time_to_happen", "immediate",
                "option", "after"
            ]
            
            try:
                target_idx = order.index(property_name)
            except ValueError:
                target_idx = len(order) - 1 # optionの手前付近

            # 挿入場所を特定
            insertion_offset = event.node.range.end_offset - 1
            insert_before_node = None
            
            if isinstance(event.node.value, ObjectNode):
                for item in event.node.value.items:
                    if isinstance(item, AssignmentNode):
                        try:
                            idx = order.index(item.key)
                        except ValueError:
                            idx = len(order) - 1
                        
                        if idx > target_idx:
                            if insert_before_node is None or item.range.start_offset < insertion_offset:
                                insertion_offset = item.range.start_offset
                                insert_before_node = item
            
            if insert_before_node:
                # 他の項目の前に挿入
                new_prop = f"{property_name} = {formatted_val}\n\t"
            else:
                # 末尾（閉じ括弧の前）に挿入
                new_prop = f"\n\t{property_name} = {formatted_val}\n"

            self.widget.content = text[:insertion_offset] + new_prop + text[insertion_offset:]

        if property_name == "id":
            self.selected_event_id = replacement
            
        self.refresh()

    def index_for_event_id(self, event_id):
        if not event_id:
            return -1
        for index, event in enumerate(self.events):
            if event.event_id == event_id:
                return index
        return -1


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


def block_text(content: str, node: Optional[AssignmentNode], name: str) -> str:
    if not node:
        return ""
    
    target_node = node
    if name:
        # 子要素から検索
        target_node = None
        if isinstance(node.value, ObjectNode):
            for item in node.value.items:
                if isinstance(item, AssignmentNode) and item.key == name:
                    target_node = item
                    break
    
    if not target_node:
        return ""

    val = target_node.value if hasattr(target_node, "value") else target_node
    if isinstance(val, ObjectNode):
        # {} の中身だけを返す
        inner = content[val.range.start_offset + 1 : val.range.end_offset - 1]
        lines = inner.strip("\r\n").splitlines()
        if not lines: return ""
        
        # 共通の最小インデント（タブまたはスペース）を削除
        import re
        margin = None
        for line in lines:
            if not line.strip(): continue
            match = re.match(r"^(\s*)", line)
            indent = match.group(1)
            if margin is None or len(indent) < len(margin):
                margin = indent
        
        if margin:
            lines = [line[len(margin):] if line.startswith(margin) else line for line in lines]
        
        return "\n".join(lines).strip("\r\n\t ")
    
    return content[val.range.start_offset : val.range.end_offset]


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
