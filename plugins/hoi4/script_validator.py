import json
import os
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Optional
from plugins.hoi4.script_parser import (
    Parser, Diagnostic, DiagnosticAction, AssignmentNode, ObjectNode, ScalarNode,
    AstNode, DocumentAst, ComparisonNode, SourceRange
)

# --- HTML ホバーポップアップ装飾ヘルパー ---
def make_error_html(title: str, detail: str, hint: str = "") -> str:
    hint_html = f'<hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.15); margin: 6px 0;"><span style="color: #888888;">{hint}</span>' if hint else ''
    return f'''<div style="font-family: 'Segoe UI', -apple-system, sans-serif; font-size: 12px; line-height: 1.4; color: #CCCCCC;">
  <b style="color: #FF5555; font-size: 13px;">🔴 [エラー] {title}</b><br>
  <span>{detail}</span>
  {hint_html}
</div>'''

def make_warning_html(title: str, detail: str, replace_with: str = "", hint: str = "") -> str:
    replace_html = ""
    if replace_with:
        replace_html = f'''<hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.15); margin: 6px 0;">
<b>推奨される代替案:</b><br>
代わりに <span style="color: #55FF55; font-weight: bold; background-color: rgba(85,255,85,0.1); border-radius: 2px; padding: 1px 4px;">{replace_with}</span> を使用してください。'''
    elif hint:
        replace_html = f'<hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.15); margin: 6px 0;"><span style="color: #888888;">{hint}</span>'
    return f'''<div style="font-family: 'Segoe UI', -apple-system, sans-serif; font-size: 12px; line-height: 1.4; color: #CCCCCC;">
  <b style="color: #FFAA00; font-size: 13px;">⚠️ [警告] {title}</b><br>
  <span>{detail}</span>
  {replace_html}
</div>'''


class ScriptValidator:
    # グローバルな限界値定数
    MAX_VALUE = 2147483
    MIN_VALUE = -2147483
    MAX_DECIMAL_PLACES = 5

    def __init__(self, plugin_path: str):
        self.plugin_path = plugin_path
        self.effects = {}
        self.triggers = {}
        
        # 検証ルールの読み込み
        effects_path = os.path.join(plugin_path, "rules", "effects.json")
        if os.path.exists(effects_path):
            try:
                with open(effects_path, "r", encoding="utf-8") as f:
                    self.effects = json.load(f)
            except Exception as e:
                print(f"Failed to load effects.json: {e}")
                
        triggers_path = os.path.join(plugin_path, "rules", "triggers.json")
        if os.path.exists(triggers_path):
            try:
                with open(triggers_path, "r", encoding="utf-8") as f:
                    self.triggers = json.load(f)
            except Exception as e:
                print(f"Failed to load triggers.json: {e}")

    def validate(self, file_path: str, content: str) -> list[Diagnostic]:
        self._content = content
        parser = Parser(content)
        ast, _, diagnostics = parser.parse()
        
        # HTMLラッピング用に既存のパーサーエラー（シンタックスエラー）をリッチHTML化する
        rich_diagnostics = []
        for d in diagnostics:
            rich_d = Diagnostic(
                severity=d.severity,
                message=make_error_html("構文エラー", d.message, hint="スクリプトの文法に誤りがあります。波括弧の対応などを確認してください。"),
                range=d.range,
                code=d.code,
                source=d.source,
                target=d.target
            )
            rich_diagnostics.append(rich_d)
        
        # スキーマの特定と読み込み
        schema = None
        norm_path = file_path.lower().replace("\\", "/")
        if "events" in norm_path:
            schema_path = os.path.join(self.plugin_path, "events", "event_schema.json")
        elif "decisions" in norm_path:
            schema_path = os.path.join(self.plugin_path, "decisions", "decision_schema.json")
        elif "interface" in norm_path:
            schema_path = os.path.join(self.plugin_path, "interface", "gfx_schema.json")
        else:
            schema_path = None
            
        if schema_path and os.path.exists(schema_path):
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema = json.load(f)
            except Exception as e:
                print(f"Failed to load schema {schema_path}: {e}")
        
        errors = []
        self._validate_node(ast, schema, None, errors)
        
        # リッチ化したパーサーエラーと、今回検出したセマンティックエラーを合算
        rich_diagnostics.extend(errors)
        return rich_diagnostics

    def _validate_node(
        self,
        node: AstNode,
        schema: Optional[dict],
        context_type: Optional[str],
        errors: list[Diagnostic],
        delete_range: Optional[SourceRange] = None,
    ):
        if isinstance(node, DocumentAst):
            for item in node.items:
                self._validate_node(item, schema, context_type, errors)
                
        elif isinstance(node, AssignmentNode):
            key = node.key
            val_node = node.value
            
            # 1. エフェクトブロック内の場合
            if context_type == "effect_block":
                if key == "limit":
                    self._validate_node(val_node, schema, "trigger_block", errors, node.range)
                elif key not in self.effects:
                    errors.append(Diagnostic(
                        severity="error",
                        message=make_error_html("未定義のエフェクト", f"エフェクト <b>{key}</b> は検証ルールに定義されていません。", hint="スペルミスがないか、または rules/effects.json に定義があるか確認してください。"),
                        range=node.key_range,
                        code="undefined-effect",
                        source="hoi4-linter"
                    ))
                else:
                    effect_rule = self.effects[key]
                    
                    # 非推奨（Deprecated）の警告
                    if effect_rule.get("deprecated"):
                        replace = effect_rule.get("replace_with", "")
                        errors.append(Diagnostic(
                            severity="warning",
                            message=make_warning_html("非推奨のエフェクト", f"エフェクト <b>{key}</b> は非推奨です。", replace_with=replace),
                            range=node.key_range,
                            code="deprecated-effect",
                            source="hoi4-linter"
                        ))
                    
                    self._check_value_type(val_node, key, effect_rule, errors, node.range)
                    
                    # 値がオブジェクトの場合は内部も同じコンテキストで再帰走査
                    if isinstance(val_node, ObjectNode):
                        self._validate_node(val_node, None, "effect_block", errors, node.range)
                    
            # 2. トリガーブロック内の場合
            elif context_type == "trigger_block":
                if key not in self.triggers:
                    errors.append(Diagnostic(
                        severity="error",
                        message=make_error_html("未定義のトリガー", f"トリガー <b>{key}</b> は検証ルールに定義されていません。", hint="スペルミスがないか、または rules/triggers.json に定義があるか確認してください。"),
                        range=node.key_range,
                        code="undefined-trigger",
                        source="hoi4-linter"
                    ))
                else:
                    trigger_rule = self.triggers[key]
                    
                    # 非推奨（Deprecated）の警告
                    if trigger_rule.get("deprecated"):
                        replace = trigger_rule.get("replace_with", "")
                        errors.append(Diagnostic(
                            severity="warning",
                            message=make_warning_html("非推奨のトリガー", f"トリガー <b>{key}</b> は非推奨です。", replace_with=replace),
                            range=node.key_range,
                            code="deprecated-trigger",
                            source="hoi4-linter"
                        ))
                    
                    self._check_value_type(val_node, key, trigger_rule, errors, node.range)
                    
                    # 値がオブジェクトの場合は内部も同じコンテキストで再帰走査
                    if isinstance(val_node, ObjectNode):
                        self._validate_node(val_node, None, "trigger_block", errors, node.range)
                    
            # 3. 通常のスキーマに沿った走査の場合
            else:
                next_context = None
                next_schema = None
                
                if schema:
                    fields = schema.get("fields", {})
                    sub_schemas = schema.get("sub_schemas", {})
                    
                    field_def = fields.get(key)
                    if field_def:
                        f_type = field_def.get("type")
                        if f_type in ("effect_block", "trigger_block"):
                            next_context = f_type
                        elif f_type == "object" and "schema" in field_def:
                            sub_name = field_def["schema"]
                            next_schema = sub_schemas.get(sub_name) or schema
                        elif f_type == "object":
                            next_schema = schema
                
                # スキーマを解決しながら再帰走査
                if isinstance(val_node, ObjectNode):
                    self._validate_node(val_node, next_schema or schema, next_context, errors, node.range)
                else:
                    self._validate_node(val_node, schema, next_context, errors)
                    
        elif isinstance(node, ObjectNode):
            # 空のコードブロックの検知 ({})
            # 内部に実質的な代入 (AssignmentNode) または 比較 (ComparisonNode) が一つもない場合
            if not any(isinstance(x, (AssignmentNode, ComparisonNode, ScalarNode, ObjectNode)) for x in node.items):
                diagnostic_range = delete_range or node.range
                errors.append(Diagnostic(
                    severity="warning",
                    message=make_warning_html("空のコードブロック", "空のコードブロックです。何も実行されません。", hint="不要な場合はこのブロックを削除してください。"),
                    range=diagnostic_range,
                    code="empty-block",
                    source="hoi4-linter",
                    actions=self._delete_empty_block_actions(diagnostic_range)
                ))
            else:
                for item in node.items:
                    self._validate_node(item, schema, context_type, errors)

    def _check_value_type(self, val_node: AstNode, key: str, rule: dict, errors: list[Diagnostic], assignment_range=None):
        expected_types = rule.get("type")
        if not expected_types:
            return
            
        # リスト形式に統一する
        if isinstance(expected_types, str):
            expected_types = [expected_types]
            
        diagnostic_range = assignment_range or val_node.range

        # 各候補型でのエラーを格納する一時リストのリスト
        all_type_errors = []
        
        for expected_type in expected_types:
            type_errors = []
            self._check_single_value_type(val_node, key, expected_type, rule, type_errors, assignment_range)
            
            # いずれかの型でエラーが発生しなかった場合、検証成功として即座に終了
            if len(type_errors) == 0:
                return
                
            all_type_errors.append(type_errors)
            
        # すべての型でエラーが検出された場合のみ、もっとも適切なエラーを報告
        # ユーザーにどの型が許容されているかを分かりやすく表示する
        type_names_map = {
            "integer": "整数",
            "float": "数値",
            "boolean": "真偽値(yes/no)",
            "country": "国タグ",
            "tag": "国タグ",
            "variable": "変数",
            "object": "オブジェクトブロック"
        }
        
        expected_names = [type_names_map.get(t, t) for t in expected_types]
        types_str = " または ".join(expected_names)
        
        errors.append(Diagnostic(
            severity="error",
            message=make_error_html("型ミスマッチ", f"<b>{key}</b> の値には <b>{types_str}</b> を指定する必要があります。"),
            range=diagnostic_range,
            code="type-mismatch",
            source="hoi4-linter"
        ))

    def _check_single_value_type(self, val_node: AstNode, key: str, expected_type: str, rule: dict, errors: list[Diagnostic], assignment_range=None):
        diagnostic_range = assignment_range or val_node.range

        def add_type_diagnostic(severity: str, message: str, code: str, actions=None):
            errors.append(Diagnostic(
                severity=severity,
                message=message,
                range=diagnostic_range,
                code=code,
                source="hoi4-linter",
                actions=actions or []
            ))
            
        if isinstance(val_node, ScalarNode):
            val_type = val_node.value_type # "int", "float", "bool", "string", "identifier"
            
            # --- グローバルな数値共通限界チェック ---
            val_num = None
            try:
                val_num = float(val_node.value)
            except (ValueError, TypeError):
                pass
                
            if val_num is not None:
                # 物理限界値 (±2,147,483) の一律オーバーフローチェック
                if val_num > self.MAX_VALUE or val_num < self.MIN_VALUE:
                    errors.append(Diagnostic(
                        severity="warning",
                        message=make_warning_html("物理限界値の超過", f"数値 <b>{val_node.raw}</b> がゲーム共通の物理限界値 (±2,147,483) を超えているため、オーバーフローする危険があります。"),
                        range=val_node.range,
                        code="overflow-warning",
                        source="hoi4-linter"
                    ))
                
                # 小数点の有効精度（小数点第5位）のチェック
                if val_type == "float" and "." in str(val_node.raw):
                    decimals = len(str(val_node.raw).split(".")[1])
                    if decimals > self.MAX_DECIMAL_PLACES:
                        errors.append(Diagnostic(
                            severity="warning",
                            message=make_warning_html("有効精度の超過", f"小数点第5位を超える値 (<b>.{str(val_node.raw).split('.')[1][5:]}</b>) は、ゲーム内で自動的に切り捨てられます。"),
                            range=val_node.range,
                            code="precision-truncated",
                            source="hoi4-linter"
                        ))
            
            # --- 想定型別の個別検証 ---
            if expected_type == "integer":
                # 数値以外は赤エラー
                if val_type not in ("int", "float"):
                    add_type_diagnostic(
                        "error",
                        make_error_html("型ミスマッチ", f"<b>{key}</b> の値には整数を指定する必要があります。", hint="真偽値(yes/no)や文字列は指定できません。"),
                        "type-mismatch",
                    )
                # 小数（.あり）は黄色警告
                elif "." in str(val_node.raw):
                    integer_actions = self._integer_fix_actions(val_node)
                    add_type_diagnostic(
                        "warning",
                        make_warning_html("整数想定への小数入力", f"<b>{key}</b> は整数 (integer) が想定されています。小数を指定すると切り捨てられます。"),
                        "integer-expected",
                        integer_actions,
                    )
                    
            elif expected_type == "float":
                # 数値（int, float）以外は赤エラー。int（ドットなし）は完全許容（波線なし）
                if val_type not in ("int", "float"):
                    add_type_diagnostic(
                        "error",
                        make_error_html("型ミスマッチ", f"<b>{key}</b> の値には数値（整数または小数）を指定する必要があります。"),
                        "type-mismatch",
                    )
                    
            elif expected_type == "boolean":
                val_str = str(val_node.raw).lower().strip()
                if val_type != "bool" and val_str not in ("yes", "no"):
                    add_type_diagnostic(
                        "error",
                        make_error_html("型ミスマッチ", f"<b>{key}</b> の値には真偽値(yes/no)を指定する必要があります。"),
                        "type-mismatch",
                    )
                else:
                    allowed = rule.get("allowed_values")
                    if allowed and val_str not in allowed:
                        add_type_diagnostic(
                            "error",
                            make_error_html("無効な値", f"<b>{key}</b> の値には {', '.join(allowed)} のいずれかを指定する必要があります。"),
                            "invalid-value",
                        )
                        
            elif expected_type in ("country", "tag"):
                val_str = str(val_node.value).strip()
                if val_type != "identifier" or len(val_str) != 3:
                    add_type_diagnostic(
                        "error",
                        make_error_html("型ミスマッチ", f"<b>{key}</b> の値には国タグ（3文字の大文字アルファベットなど）を指定する必要があります。"),
                        "type-mismatch",
                    )
                    
        elif isinstance(val_node, ObjectNode):
            if expected_type != "object":
                add_type_diagnostic(
                    "error",
                    make_error_html("型ミスマッチ", f"<b>{key}</b> の値にオブジェクトブロックを指定することはできません。"),
                    "type-mismatch",
                )
            else:
                # オブジェクト想定の中身が空ブロックであるかチェック
                if not any(isinstance(x, (AssignmentNode, ComparisonNode)) for x in val_node.items):
                    diagnostic_range = assignment_range or val_node.range
                    errors.append(Diagnostic(
                        severity="warning",
                        message=make_warning_html("空のコードブロック", f"ブロック <b>{key}</b> の中身が空です。何も実行されません。"),
                        range=diagnostic_range,
                        code="empty-block",
                        source="hoi4-linter",
                        actions=self._delete_empty_block_actions(diagnostic_range)
                    ))

    def _delete_empty_block_actions(self, source_range: SourceRange) -> list[DiagnosticAction]:
        return [DiagnosticAction("ブロックを削除", source_range, "")]

    def _integer_fix_actions(self, val_node: ScalarNode) -> list[DiagnosticAction]:
        try:
            value = Decimal(str(val_node.raw))
        except InvalidOperation:
            return []

        truncated = value.to_integral_value(rounding=ROUND_DOWN)
        rounded = value.to_integral_value(rounding=ROUND_HALF_UP)
        actions = [
            DiagnosticAction(f"{truncated} に切り捨て", val_node.range, str(truncated)),
        ]
        if rounded != truncated:
            actions.append(DiagnosticAction(f"{rounded} に丸め", val_node.range, str(rounded)))
        return actions
