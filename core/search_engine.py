import re
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QTextDocument, QTextCursor, QTextBlock

class SearchQuery:
    """検索キーワードとオプション条件（正規表現、大文字小文字区別、単語単位）を保持・解析するクラス"""
    def __init__(self, search_text: str = "", match_case: bool = False, use_regex: bool = False, whole_word: bool = False):
        self.search_text = search_text
        self.match_case = match_case
        self.use_regex = use_regex
        self.whole_word = whole_word

    def is_empty(self) -> bool:
        return not self.search_text

    def to_regular_expression(self) -> QRegularExpression:
        """条件に基づいた QRegularExpression オブジェクトを構築して返します"""
        if self.is_empty():
            return QRegularExpression()

        pattern = self.search_text
        
        # 正規表現を使用しない場合は、メタ文字をエスケープする
        if not self.use_regex:
            pattern = QRegularExpression.escape(pattern)

        # 単語単位での一致を反映
        if self.whole_word:
            # 正規表現のエスケープ文字に対応するため \\b を使用
            pattern = f"\\b{pattern}\\b"

        # 大文字小文字の区別オプション
        options = QRegularExpression.PatternOption.NoPatternOption
        if not self.match_case:
            options |= QRegularExpression.PatternOption.CaseInsensitiveOption

        return QRegularExpression(pattern, options)


class SearchOccurrence:
    """テキスト内での1箇所の一致箇所を表すデータクラス"""
    def __init__(self, position: int, length: int, line_number: int, line_text: str):
        self.position = position          # ドキュメント内での絶対開始位置
        self.length = length              # マッチした長さ
        self.line_number = line_number    # 1から始まる行番号
        self.line_text = line_text        # 一致箇所の行全体のプレビューテキスト

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "length": self.length,
            "line_number": self.line_number,
            "line_text": self.line_text
        }


class TextDocumentSearcher:
    """QTextDocumentに対するテキスト検索を実行するクラス"""
    
    @staticmethod
    def search(document: QTextDocument, query: SearchQuery) -> list[SearchOccurrence]:
        """QTextDocument内を走査し、SearchQueryに一致するすべての箇所を抽出して返します"""
        occurrences = []
        if not document or query.is_empty():
            return occurrences

        q_regex = query.to_regular_expression()
        if not q_regex.isValid():
            return occurrences

        # QTextDocument の find() メソッドを用いて順方向スキャン
        cursor = QTextCursor(document)
        
        while True:
            # find は現在カーソル位置から検索を開始し、見つかった場合に新しい位置のカーソルを返す
            # QTextDocument.FindFlag を指定しない場合は、正規表現マッチが前方スキャンされる
            cursor = document.find(q_regex, cursor)
            if cursor.isNull():
                break

            # マッチした箇所の情報抽出
            position = cursor.selectionStart()
            length = cursor.selectionEnd() - position
            
            # 行情報の取得
            block = cursor.block()
            line_number = block.blockNumber() + 1 # blockNumberは0始まり
            line_text = block.text()

            occurrence = SearchOccurrence(
                position=position,
                length=length,
                line_number=line_number,
                line_text=line_text
            )
            occurrences.append(occurrence)

        return occurrences
