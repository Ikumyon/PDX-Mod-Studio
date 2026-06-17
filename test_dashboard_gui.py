import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from PySide6.QtWidgets import QApplication, QMainWindow
from core.dashboard_tab_host import renderer_registry
from lib.pdx_dashboard.renderer import DashboardTextRenderer

def run_test():
    app = QApplication(sys.argv)
    
    # レンダラーの翻訳をインストール
    renderer_registry.install_translations(app)
    
    test_data = """
# Japan Rework (TEST DATA)

game: hoi4
version: 1.14.6

[metrics]
focuses: 156
events: 92
decisions: 41
total_loc: 1000
untranslated_loc: 235
errors: 3
"""
    
    window = QMainWindow()
    window.setWindowTitle("Dashboard Test (Clausewitz Library with i18n)")
    window.resize(800, 450)
    
    # 背景色をダークテーマに設定
    window.setStyleSheet("QMainWindow { background-color: #1e1e1e; }")
    
    renderer = DashboardTextRenderer()
    widget = renderer.render(test_data)
    
    window.setCentralWidget(widget)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    run_test()
