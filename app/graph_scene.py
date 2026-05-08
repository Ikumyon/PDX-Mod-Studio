from PySide6.QtWidgets import QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem, QGraphicsLineItem, QGraphicsEllipseItem
from PySide6.QtCore import Qt, QPointF, QLineF
from PySide6.QtGui import QPen, QBrush, QColor
import math

class NodeItem(QGraphicsEllipseItem):
    def __init__(self, res_type, res_id, pos):
        super().__init__(-50, -25, 100, 50)
        self.res_type = res_type
        self.res_id = res_id
        self.setPos(pos)
        
        self.setBrush(QBrush(QColor("#2d2d2d")))
        self.setPen(QPen(QColor("#007acc"), 2))
        self.setFlags(QGraphicsEllipseItem.ItemIsMovable | QGraphicsEllipseItem.ItemIsSelectable | QGraphicsEllipseItem.ItemSendsGeometryChanges)
        
        # テキスト
        display_text = f"{res_type}\n{res_id}"
        self.label = QGraphicsTextItem(display_text, self)
        self.label.setDefaultTextColor(QColor("white"))
        # 中央寄せ
        br = self.label.boundingRect()
        self.label.setPos(-br.width()/2, -br.height()/2)
        
        self.edges = []

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.ItemPositionHasChanged:
            for edge in self.edges:
                edge.update_position()
        return super().itemChange(change, value)

class EdgeItem(QGraphicsLineItem):
    def __init__(self, source_item, target_item):
        super().__init__()
        self.source = source_item
        self.target = target_item
        self.setPen(QPen(QColor("#666666"), 1))
        self.setZValue(-1)
        
        self.source.edges.append(self)
        self.target.edges.append(self)
        self.update_position()
        
    def update_position(self):
        line = QLineF(self.source.scenePos(), self.target.scenePos())
        self.setLine(line)

class DependencyGraphScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes = {} # (type, id) -> NodeItem

    def build_graph(self, graph):
        self.clear()
        self.nodes = {}
        
        all_nodes_list = list(graph.all_nodes)
        count = len(all_nodes_list)
        if count == 0: return
        
        # 円形配置
        radius = max(200, count * 30)
        for i, node_key in enumerate(all_nodes_list):
            angle = 2 * math.pi * i / count
            pos = QPointF(radius * math.cos(angle), radius * math.sin(angle))
            
            node_item = NodeItem(node_key[0], node_key[1], pos)
            self.addItem(node_item)
            self.nodes[node_key] = node_item
            
        # エッジの追加
        for source, targets in graph.forward_refs.items():
            if source not in self.nodes: continue
            src_item = self.nodes[source]
            for target in targets:
                if target in self.nodes:
                    edge = EdgeItem(src_item, self.nodes[target])
                    self.addItem(edge)
