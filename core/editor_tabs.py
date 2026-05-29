import os
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QTabBar, QStackedWidget, QVBoxLayout, QHBoxLayout

def set_zero_margins(layout):
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

# QTabBar をプログラム側で生成（QUiLoader の制限回避）
def create_editor_tab_bar(parent):
    tab_bar = QTabBar(parent)
    tab_bar.setDocumentMode(True)
    tab_bar.setTabsClosable(True)
    tab_bar.setExpanding(False)
    return tab_bar

def create_editor_pane(index, editor_splitter):
    pane = QWidget(editor_splitter)
    pane.setObjectName(f"editorPane{index}")

    pane_layout = QVBoxLayout(pane)
    set_zero_margins(pane_layout)

    header_layout = QHBoxLayout()
    set_zero_margins(header_layout)

    tab_container = QWidget(pane)
    tab_container.setObjectName(f"editorTabBarContainer{index}")
    tab_container_layout = QHBoxLayout(tab_container)
    set_zero_margins(tab_container_layout)

    tab_bar = create_editor_tab_bar(tab_container)
    tab_container_layout.addWidget(tab_bar)

    corner_container = QWidget(pane)
    corner_container.setObjectName(f"tabCornerContainer{index}")
    corner_layout = QHBoxLayout(corner_container)
    corner_layout.setContentsMargins(0, 0, 10, 0)
    corner_layout.setSpacing(6)

    header_layout.addWidget(tab_container)
    header_layout.addStretch(1)
    header_layout.addWidget(corner_container)

    stack = QStackedWidget(pane)
    stack.setObjectName(f"editorStackedWidget{index}")

    pane_layout.addLayout(header_layout)
    pane_layout.addWidget(stack)

    return {
        "id": f"pane:{index}",
        "widget": pane,
        "tab_bar": tab_bar,
        "stack": stack,
        "corner": corner_container,
    }

class EditorTabProxy(QWidget):
    tabCloseRequested = Signal(int)
    currentChanged = Signal(int)

    def __init__(self, splitter, first_pane):
        super().__init__()
        self.splitter = splitter
        self._panes = []
        self._records = []
        self._active_pane = first_pane
        self._current_index = -1
        self._mutating_tabs = False
        self._next_pane_id = 1
        self._register_pane(first_pane)

    def _register_pane(self, pane):
        self._panes.append(pane)
        pane["tab_bar"].currentChanged.connect(
            lambda local_index, p=pane: self._on_local_current_changed(p, local_index)
        )
        pane["tab_bar"].tabCloseRequested.connect(
            lambda local_index, p=pane: self._on_local_tab_close_requested(p, local_index)
        )

    def _pane_index(self, pane):
        for index, candidate in enumerate(self._panes):
            if candidate is pane:
                return index
        return -1

    def _create_pane_after(self, pane):
        new_pane = create_editor_pane(self._next_pane_id, self.splitter)
        self._next_pane_id += 1
        pane_index = self._pane_index(pane)
        insert_at = pane_index + 1 if pane_index >= 0 else len(self._panes)
        self._panes.insert(insert_at, new_pane)
        self.splitter.insertWidget(insert_at, new_pane["widget"])
        new_pane["tab_bar"].currentChanged.connect(
            lambda local_index, p=new_pane: self._on_local_current_changed(p, local_index)
        )
        new_pane["tab_bar"].tabCloseRequested.connect(
            lambda local_index, p=new_pane: self._on_local_tab_close_requested(p, local_index)
        )
        self._active_pane = new_pane
        self._rebalance_splitter()
        return new_pane

    def createPaneAfterActive(self):
        return self._create_pane_after(self._active_pane)

    def _records_for_pane(self, pane):
        return [record for record in self._records if record["pane"] is pane]

    def _pane_for_tab(self, pane):
        return pane if self._pane_index(pane) >= 0 else self._active_pane

    def _remove_empty_pane(self, pane):
        pane_index = self._pane_index(pane)
        if pane_index < 0 or len(self._panes) <= 1 or self._records_for_pane(pane):
            return
        self._panes.pop(pane_index)
        pane["widget"].setParent(None)
        pane["widget"].deleteLater()
        if self._active_pane is pane:
            self._active_pane = self._panes[min(pane_index, len(self._panes) - 1)]
        self._rebalance_splitter()

    def _rebalance_splitter(self):
        pane_count = len(self._panes)
        if pane_count > 0:
            self.splitter.setSizes([1] * pane_count)

    def _global_index_for_local(self, pane, local_index):
        if local_index < 0:
            return -1
        current_local_index = -1
        for global_index, record in enumerate(self._records):
            if record["pane"] is not pane:
                continue
            current_local_index += 1
            if current_local_index == local_index:
                return global_index
        return -1

    def _local_index_for_global(self, index):
        if index < 0 or index >= len(self._records):
            return None, -1
        record = self._records[index]
        pane = record["pane"]
        local_index = 0
        for i, candidate in enumerate(self._records):
            if i == index:
                return pane, local_index
            if candidate["pane"] is pane:
                local_index += 1
        return None, -1

    def _activate_index(self, index, should_emit=False):
        if index < 0 or index >= len(self._records):
            return
        previous_index = self._current_index
        record = self._records[index]
        pane = record["pane"]
        stack = pane["stack"]
        widget = record["widget"]
        if stack.indexOf(widget) >= 0:
            stack.setCurrentWidget(widget)
        self._active_pane = pane
        self._current_index = index
        if should_emit and previous_index != index:
            self.currentChanged.emit(index)

    def _on_local_current_changed(self, pane, local_index):
        if self._mutating_tabs:
            return
        index = self._global_index_for_local(pane, local_index)
        if index >= 0:
            self._activate_index(index, should_emit=True)

    def _on_local_tab_close_requested(self, pane, local_index):
        index = self._global_index_for_local(pane, local_index)
        if index >= 0:
            self.tabCloseRequested.emit(index)

    def setCurrentWidget(self, widget):
        index = self.indexOf(widget)
        if index >= 0:
            self.setCurrentIndex(index)
            return True
        return False

    def focusWidgetChanged(self, widget):
        while widget:
            if self.setCurrentWidget(widget):
                return True
            widget = widget.parentWidget()
        return False

    def count(self): return len(self._records)
    def activePane(self): return self._active_pane
    def activeCornerLayout(self):
        corner = self._active_pane.get("corner") if self._active_pane else None
        return corner.layout() if corner else None
    def currentIndex(self): return self._current_index
    def currentWidget(self): return self.widget(self.currentIndex())
    def setCurrentIndex(self, index):
        if index < 0 or index >= self.count():
            if self._current_index != -1:
                self._current_index = -1
                self.currentChanged.emit(-1)
            return
        pane, local_index = self._local_index_for_global(index)
        if pane is None:
            return
        tab_bar = pane["tab_bar"]
        if tab_bar.currentIndex() == local_index:
            self._activate_index(index, should_emit=True)
        else:
            tab_bar.setCurrentIndex(local_index)
    def widget(self, index):
        if index < 0 or index >= len(self._records):
            return None
        return self._records[index]["widget"]

    def _tab_bar_and_local_index(self, index):
        pane, local_index = self._local_index_for_global(index)
        if pane is None:
            return None, -1
        return pane["tab_bar"], local_index

    def tabText(self, index):
        tab_bar, local_index = self._tab_bar_and_local_index(index)
        return tab_bar.tabText(local_index) if tab_bar else ""
    def setTabText(self, index, text):
        tab_bar, local_index = self._tab_bar_and_local_index(index)
        if tab_bar:
            tab_bar.setTabText(local_index, text)
    def tabToolTip(self, index):
        tab_bar, local_index = self._tab_bar_and_local_index(index)
        return tab_bar.tabToolTip(local_index) if tab_bar else ""
    def setTabToolTip(self, index, tip):
        tab_bar, local_index = self._tab_bar_and_local_index(index)
        if tab_bar:
            tab_bar.setTabToolTip(local_index, tip)
    def tabIcon(self, index):
        tab_bar, local_index = self._tab_bar_and_local_index(index)
        return tab_bar.tabIcon(local_index) if tab_bar else None
    def setTabIcon(self, index, icon):
        tab_bar, local_index = self._tab_bar_and_local_index(index)
        if tab_bar:
            tab_bar.setTabIcon(local_index, icon)
    def removeTab(self, index):
        if index < 0 or index >= len(self._records):
            return
        tab_bar, local_index = self._tab_bar_and_local_index(index)
        record = self._records.pop(index)
        w = record["widget"]
        pane = record["pane"]
        stack = pane["stack"]
        self._mutating_tabs = True
        if tab_bar:
            tab_bar.removeTab(local_index)
        if w:
            stack.removeWidget(w)
            w.deleteLater()
        self._mutating_tabs = False
        self._remove_empty_pane(pane)
        if self.count() > 0:
            self.setCurrentIndex(min(index, self.count() - 1))
        elif self._current_index != -1:
            self._current_index = -1
            self.currentChanged.emit(-1)
    def addTab(self, widget, icon, text):
        return self.addTabToPane(widget, icon, text, self._active_pane)
    def addTabToPane(self, widget, icon, text, pane):
        pane = self._pane_for_tab(pane)
        pane["stack"].addWidget(widget)
        self._records.append({"widget": widget, "pane": pane})
        self._mutating_tabs = True
        pane["tab_bar"].addTab(icon, text)
        self._mutating_tabs = False
        return len(self._records) - 1
    def insertTab(self, index, widget, icon, text):
        if index < 0 or index > len(self._records):
            index = len(self._records)
        pane = self._active_pane
        pane["stack"].addWidget(widget)
        local_index = sum(1 for record in self._records[:index] if record["pane"] is pane)
        self._records.insert(index, {"widget": widget, "pane": pane})
        self._mutating_tabs = True
        pane["tab_bar"].insertTab(local_index, icon, text)
        self._mutating_tabs = False
        return index
    def indexOf(self, widget):
        for index, record in enumerate(self._records):
            if record["widget"] is widget:
                return index
        return -1
    def setCornerWidget(self, widget, corner):
        if self._active_pane and self._active_pane.get("corner"):
            # 既存のウィジェットのうち、固定ボタン以外を削除
            layout = self._active_pane["corner"].layout()
            for i in reversed(range(layout.count())):
                item = layout.itemAt(i)
                w = item.widget()
                if w and w.objectName() not in ("modeSelectorButton", "splitEditorButton"):
                    layout.removeItem(item)
                    w.deleteLater()
            layout.addWidget(widget)
