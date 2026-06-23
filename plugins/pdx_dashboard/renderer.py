from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from core.i18n import tr
from plugins.pdx_dashboard.parser import DashboardTextParser

class DashboardTextRenderer:
    def get_translation_info(self) -> dict:
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        loc_dir = os.path.join(base_dir, "localisation")
        return {
            "directory": loc_dir,
            "filename": "pdx_dashboard"
        }

    def render(self, payload: str, context: dict = None) -> QWidget:
        # 1. パース処理
        data = DashboardTextParser.parse(payload)
        
        # 2. メインコンテナの作成
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)
        
        # 3. タイトル
        if data["title"]:
            title_label = QLabel(data["title"])
            title_font = QFont()
            title_font.setPointSize(24)
            title_font.setBold(True)
            title_label.setFont(title_font)
            title_label.setStyleSheet("color: #ffffff; margin-bottom: 5px;")
            main_layout.addWidget(title_label)
            
        # 4. メタデータ (ゲーム名、対応バージョン)
        if data["meta"]:
            meta_layout = QHBoxLayout()
            meta_layout.setSpacing(20)
            
            game_id = data["meta"].get("game")
            if game_id:
                # 翻訳キーでゲーム名を解決
                game_name = tr(f"dashboard.game.{game_id}")
                lbl_game = QLabel(f"{tr('dashboard.metadata.game')}: {game_name}")
                lbl_game.setStyleSheet("color: #aaaaaa; font-size: 11pt;")
                meta_layout.addWidget(lbl_game)
                
            version = data["meta"].get("version")
            if version:
                lbl_ver = QLabel(f"{tr('dashboard.metadata.version')}: {version}")
                lbl_ver.setStyleSheet("color: #aaaaaa; font-size: 11pt;")
                meta_layout.addWidget(lbl_ver)
                
            meta_layout.addStretch()
            main_layout.addLayout(meta_layout)
            
        # 区切り線
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #333333; max-height: 1px;")
        main_layout.addWidget(line)
        
        # 5. 指標 (metrics) セクションの構築
        if data["metrics"]:
            metrics_container = QWidget()
            metrics_layout = QGridLayout(metrics_container)
            metrics_layout.setContentsMargins(0, 10, 0, 10)
            metrics_layout.setSpacing(15)
            
            # 各指標カードのスタイル
            card_style = """
                QFrame {
                    background-color: #252526;
                    border: 1px solid #3c3c3c;
                    border-radius: 8px;
                    padding: 15px;
                }
                QFrame:hover {
                    border-color: #007acc;
                    background-color: #2d2d30;
                }
            """
            
            # 描画対象の定義 (スロットID、翻訳キー、表示用値、配置順序インデックス)
            card_items = []
            
            # 汎用メトリクス
            for key in ("focuses", "events", "decisions", "errors"):
                val = data["metrics"].get(key)
                if val is not None:
                    card_items.append((
                        key,
                        tr(f"dashboard.metrics.{key}"),
                        str(val)
                    ))
            
            # 未翻訳 (total_loc と untranslated_loc から進捗割合と分数を算出)
            total = data["metrics"].get("total_loc")
            untranslated = data["metrics"].get("untranslated_loc")
            if total is not None and untranslated is not None:
                try:
                    total_val = int(total)
                    untranslated_val = int(untranslated)
                    if total_val > 0:
                        percent = (untranslated_val / total_val) * 100
                        value_str = f"{percent:.1f}% ({untranslated_val}/{total_val})"
                    else:
                        value_str = f"0.0% (0/{total_val})"
                except (ValueError, TypeError):
                    value_str = f"{untranslated}/{total}"
                    
                card_items.append((
                    "untranslated",
                    tr("dashboard.metrics.untranslated"),
                    value_str
                ))
            
            # 最大4列でカードを配置
            col_count = 4
            for i, (slot_id, label_text, value_text) in enumerate(card_items):
                card = QFrame()
                card.setFrameShape(QFrame.StyledPanel)
                card.setStyleSheet(card_style)
                
                card_layout = QVBoxLayout(card)
                card_layout.setSpacing(5)
                
                val_lbl = QLabel(value_text)
                val_font = QFont()
                val_font.setPointSize(18)
                val_font.setBold(True)
                val_lbl.setFont(val_font)
                val_lbl.setAlignment(Qt.AlignCenter)
                val_lbl.setStyleSheet("color: #007acc; border: none; background: transparent;")
                
                key_lbl = QLabel(label_text)
                key_lbl.setFont(QFont("Arial", 9))
                key_lbl.setAlignment(Qt.AlignCenter)
                key_lbl.setStyleSheet("color: #888888; border: none; background: transparent;")
                
                card_layout.addWidget(val_lbl)
                card_layout.addWidget(key_lbl)
                
                row = i // col_count
                col = i % col_count
                metrics_layout.addWidget(card, row, col)
                
            main_layout.addWidget(metrics_container)
            
        main_layout.addStretch()
        return container
