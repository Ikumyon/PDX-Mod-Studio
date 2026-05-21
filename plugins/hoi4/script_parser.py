from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

@dataclass(frozen=True)
class SourcePosition:
    offset: int
    line: int
    column: int

@dataclass(frozen=True)
class SourceRange:
    start: SourcePosition
    end: SourcePosition

    @property
    def start_offset(self) -> int: return self.start.offset
    @property
    def end_offset(self) -> int: return self.end.offset

    @staticmethod
    def between(start: SourceRange, end: SourceRange) -> SourceRange:
        return SourceRange(start.start, end.end)

@dataclass(frozen=True)
class DiagnosticAction:
    title: str
    range: SourceRange
    replacement: str

@dataclass
class Diagnostic:
    severity: str
    message: str
    range: SourceRange
    code: Optional[str] = None
    source: Optional[str] = None
    target: Any = None
    actions: list[DiagnosticAction] = field(default_factory=list)


class TokenKind(str, Enum):
    IDENT = "identifier"
    STRING = "string"
    NUMBER = "number"
    EQUALS = "equals"
    LBRACE = "lbrace"
    RBRACE = "rbrace"
    COMPARISON = "comparison"
    COMMENT = "comment"
    WHITESPACE = "whitespace"
    NEWLINE = "newline"
    EOF = "eof"
    INVALID = "invalid"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    raw: str
    range: SourceRange


@dataclass
class AstNode:
    range: SourceRange


@dataclass
class DocumentAst(AstNode):
    items: list[AstNode] = field(default_factory=list)


@dataclass
class AssignmentNode(AstNode):
    key: str
    value: AstNode
    key_range: SourceRange
    operator_range: SourceRange


@dataclass
class ObjectNode(AstNode):
    items: list[AstNode] = field(default_factory=list)
    open_range: Optional[SourceRange] = None
    close_range: Optional[SourceRange] = None

    def assignments(self, key: Optional[str] = None) -> list[AssignmentNode]:
        result = [item for item in self.items if isinstance(item, AssignmentNode)]
        if key is not None:
            result = [item for item in result if item.key == key]
        return result

    def first_assignment(self, key: str) -> Optional[AssignmentNode]:
        matches = self.assignments(key)
        return matches[0] if matches else None


@dataclass
class ScalarNode(AstNode):
    value: Any
    raw: str
    value_type: str


@dataclass
class ComparisonNode(AstNode):
    left: ScalarNode
    operator: str
    right: AstNode
    operator_range: SourceRange


@dataclass
class MissingValueNode(AstNode):
    pass


@dataclass
class ErrorNode(AstNode):
    message: str
    raw: str = ""


class Lexer:
    COMPARISON_OPERATORS = ("<=", ">=", "==", "!=", "<", ">")

    def __init__(self, text: str):
        self.text = text
        self.offset = 0
        self.line = 1
        self.column = 1
        self.diagnostics: list[Diagnostic] = []

    def tokenize(self) -> tuple[list[Token], list[Diagnostic]]:
        tokens: list[Token] = []
        while not self._is_at_end():
            ch = self._peek()
            if ch in " \t\f\v":
                tokens.append(self._read_while(TokenKind.WHITESPACE, lambda c: c in " \t\f\v"))
            elif ch in "\r\n":
                tokens.append(self._read_newline())
            elif ch == "#":
                tokens.append(self._read_comment())
            elif ch == '"':
                tokens.append(self._read_string())
            elif ch == "{":
                tokens.append(self._single(TokenKind.LBRACE))
            elif ch == "}":
                tokens.append(self._single(TokenKind.RBRACE))
            elif ch == "=":
                if self._peek(1) == "=":
                    tokens.append(self._fixed(TokenKind.COMPARISON, "=="))
                else:
                    tokens.append(self._single(TokenKind.EQUALS))
            elif self._starts_comparison():
                op = next(op for op in self.COMPARISON_OPERATORS if self.text.startswith(op, self.offset))
                tokens.append(self._fixed(TokenKind.COMPARISON, op))
            elif self._starts_number():
                tokens.append(self._read_number())
            elif self._starts_identifier(ch):
                tokens.append(self._read_identifier())
            else:
                token = self._single(TokenKind.INVALID)
                self.diagnostics.append(
                    Diagnostic(
                        severity="error",
                        message=f"Invalid character: {token.raw!r}",
                        range=token.range,
                        code="invalid-character",
                        source="hoi4-lexer",
                    )
                )
                tokens.append(token)

        eof_position = self._position()
        tokens.append(Token(TokenKind.EOF, "", "", SourceRange(eof_position, eof_position)))
        return tokens, self.diagnostics

    def _position(self) -> SourcePosition:
        return SourcePosition(self.offset, self.line, self.column)

    def _is_at_end(self) -> bool:
        return self.offset >= len(self.text)

    def _peek(self, distance: int = 0) -> str:
        index = self.offset + distance
        return "" if index >= len(self.text) else self.text[index]

    def _advance(self) -> str:
        ch = self.text[self.offset]
        self.offset += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _single(self, kind: TokenKind) -> Token:
        start = self._position()
        raw = self._advance()
        return Token(kind, raw, raw, SourceRange(start, self._position()))

    def _fixed(self, kind: TokenKind, raw: str) -> Token:
        start = self._position()
        for _ in raw:
            self._advance()
        return Token(kind, raw, raw, SourceRange(start, self._position()))

    def _read_while(self, kind: TokenKind, predicate) -> Token:
        start = self._position()
        raw = []
        while not self._is_at_end() and predicate(self._peek()):
            raw.append(self._advance())
        text = "".join(raw)
        return Token(kind, text, text, SourceRange(start, self._position()))

    def _read_newline(self) -> Token:
        start = self._position()
        if self._peek() == "\r" and self._peek(1) == "\n":
            self._advance()
            self._advance()
            raw = "\r\n"
        else:
            raw = self._advance()
        return Token(TokenKind.NEWLINE, raw, raw, SourceRange(start, self._position()))

    def _read_comment(self) -> Token:
        return self._read_while(TokenKind.COMMENT, lambda c: c not in "\r\n")

    def _read_string(self) -> Token:
        start = self._position()
        raw = [self._advance()]
        value = []
        escaped = False

        while not self._is_at_end():
            ch = self._advance()
            raw.append(ch)
            if escaped:
                value.append(ch)
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                return Token(TokenKind.STRING, "".join(value), "".join(raw), SourceRange(start, self._position()))
            else:
                value.append(ch)

        token = Token(TokenKind.STRING, "".join(value), "".join(raw), SourceRange(start, self._position()))
        self.diagnostics.append(
            Diagnostic("error", "Unterminated string literal", token.range, code="unterminated-string", source="hoi4-lexer")
        )
        return token

    def _read_number(self) -> Token:
        start = self._position()
        raw = []
        if self._peek() in "+-":
            raw.append(self._advance())
        while not self._is_at_end() and self._peek().isdigit():
            raw.append(self._advance())
        if self._peek() == "." and self._peek(1).isdigit():
            raw.append(self._advance())
            while not self._is_at_end() and self._peek().isdigit():
                raw.append(self._advance())
        text = "".join(raw)
        return Token(TokenKind.NUMBER, text, text, SourceRange(start, self._position()))

    def _read_identifier(self) -> Token:
        return self._read_while(TokenKind.IDENT, self._is_identifier_char)

    def _starts_number(self) -> bool:
        ch = self._peek()
        return ch.isdigit() or (ch in "+-" and self._peek(1).isdigit())

    def _starts_comparison(self) -> bool:
        return any(self.text.startswith(op, self.offset) for op in self.COMPARISON_OPERATORS)

    def _starts_identifier(self, ch: str) -> bool:
        return ch.isalpha() or ch in "_."

    def _is_identifier_char(self, ch: str) -> bool:
        return ch.isalnum() or ch in "_.:/@$%+-"


TRIVIA = {TokenKind.WHITESPACE, TokenKind.NEWLINE, TokenKind.COMMENT}
SCALAR = {TokenKind.IDENT, TokenKind.STRING, TokenKind.NUMBER}


class Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens, self.diagnostics = Lexer(text).tokenize()
        self.index = 0

    def parse(self) -> tuple[DocumentAst, list[Token], list[Diagnostic]]:
        start = self._current().range
        items: list[AstNode] = []
        while not self._check(TokenKind.EOF):
            self._skip_trivia()
            if self._check(TokenKind.EOF):
                break
            items.append(self._parse_statement())
        end = self._current().range
        return DocumentAst(SourceRange.between(start, end), items), self.tokens, self.diagnostics

    def _parse_statement(self) -> AstNode:
        self._skip_trivia()
        token = self._current()
        if token.kind in SCALAR:
            left = self._parse_scalar()
            self._skip_trivia()
            if self._match(TokenKind.EQUALS):
                operator = self._previous()
                value = self._parse_value()
                return AssignmentNode(SourceRange.between(left.range, value.range), str(left.value), value, left.range, operator.range)
            if self._match(TokenKind.COMPARISON):
                operator = self._previous()
                right = self._parse_value()
                return ComparisonNode(SourceRange.between(left.range, right.range), left, operator.value, right, operator.range)
            return left
        if self._check(TokenKind.LBRACE):
            return self._parse_object()
        bad = self._advance()
        node = ErrorNode(bad.range, f"Unexpected token: {bad.raw!r}", bad.raw)
        self.diagnostics.append(Diagnostic("error", node.message, bad.range, code="unexpected-token", source="hoi4-parser", target=node))
        return node

    def _parse_value(self) -> AstNode:
        self._skip_trivia()
        if self._check(TokenKind.EOF) or self._check(TokenKind.RBRACE):
            token = self._current()
            node = MissingValueNode(token.range)
            self.diagnostics.append(Diagnostic("error", "Missing value", token.range, code="missing-value", source="hoi4-parser", target=node))
            return node
        if self._check(TokenKind.LBRACE):
            return self._parse_object()
        if self._current().kind in SCALAR:
            return self._parse_scalar()
        bad = self._advance()
        node = ErrorNode(bad.range, f"Invalid value token: {bad.raw!r}", bad.raw)
        self.diagnostics.append(Diagnostic("error", node.message, bad.range, code="invalid-value", source="hoi4-parser", target=node))
        return node

    def _parse_object(self) -> ObjectNode:
        open_token = self._consume(TokenKind.LBRACE, "Expected '{'")
        items: list[AstNode] = []
        close_token = None
        while not self._check(TokenKind.EOF):
            self._skip_trivia()
            if self._match(TokenKind.RBRACE):
                close_token = self._previous()
                break
            items.append(self._parse_statement())
        if close_token is None:
            end_range = self._current().range
            self.diagnostics.append(Diagnostic("error", "Missing closing brace", end_range, code="missing-closing-brace", source="hoi4-parser"))
        else:
            end_range = close_token.range
        return ObjectNode(SourceRange.between(open_token.range, end_range), items, open_token.range, close_token.range if close_token else None)

    def _parse_scalar(self) -> ScalarNode:
        token = self._advance()
        if token.kind == TokenKind.NUMBER:
            value_type = "float" if "." in token.value else "int"
            value = float(token.value) if value_type == "float" else int(token.value)
        elif token.kind == TokenKind.STRING:
            value_type = "string"
            value = token.value
        elif token.value in {"yes", "no", "true", "false"}:
            value_type = "bool"
            value = token.value in {"yes", "true"}
        else:
            value_type = "identifier"
            value = token.value
        return ScalarNode(token.range, value, token.raw, value_type)

    def _skip_trivia(self) -> None:
        while self._current().kind in TRIVIA:
            self._advance()

    def _match(self, kind: TokenKind) -> bool:
        if self._check(kind):
            self._advance()
            return True
        return False

    def _consume(self, kind: TokenKind, message: str) -> Token:
        if self._check(kind):
            return self._advance()
        token = self._current()
        self.diagnostics.append(Diagnostic("error", message, token.range, code="expected-token", source="hoi4-parser"))
        return token

    def _check(self, kind: TokenKind) -> bool:
        return self._current().kind == kind

    def _advance(self) -> Token:
        if not self._check(TokenKind.EOF):
            self.index += 1
        return self.tokens[self.index - 1]

    def _current(self) -> Token:
        return self.tokens[self.index]

    def _previous(self) -> Token:
        return self.tokens[self.index - 1]


def node_value(node: AstNode) -> Any:
    if isinstance(node, ScalarNode):
        return node.value
    if isinstance(node, ObjectNode):
        return node
    return None


def value_range(node: AstNode) -> SourceRange:
    return node.range


def infer_value_type(node: AstNode) -> str:
    if isinstance(node, ScalarNode):
        return node.value_type
    if isinstance(node, ObjectNode):
        return "object"
    return "raw"


@dataclass
class ParsedEntity:
    schema_name: str
    id: str
    parent_id: Optional[str]
    properties: dict[str, list[AssignmentNode]] = field(default_factory=dict)
    node: Optional[AstNode] = field(default=None)
    source_path: str = ""
    case_insensitive_keys: bool = False

    def first(self, key: str) -> Optional[AssignmentNode]:
        actual_key = self.actual_key(key)
        nodes = self.properties.get(actual_key, []) if actual_key else []
        return nodes[0] if nodes else None

    def actual_key(self, key: str) -> Optional[str]:
        if key in self.properties:
            return key
        if not self.case_insensitive_keys:
            return None
        key_lower = key.lower()
        for property_key in self.properties.keys():
            if property_key.lower() == key_lower:
                return property_key
        return None

class SchemaEvaluator:
    def __init__(self, schema: dict):
        self.schema = schema
        self.schema_name = schema.get("schema_name", "unknown")
        self.root_pattern = schema.get("root_pattern", "named_block")
        self.id_rule = schema.get("id_rule", {})
        self.fields = schema.get("fields", {})
        self.case_insensitive_keys = bool(schema.get("case_insensitive_keys", False))

    def evaluate(self, ast: AstNode, path: str = "") -> list[ParsedEntity]:
        entities: list[ParsedEntity] = []
        if not hasattr(ast, "items"):
            return entities

        if self.root_pattern == "named_block":
            for item in getattr(ast, "items", []):
                if not isinstance(item, AssignmentNode) or not isinstance(item.value, ObjectNode):
                    continue
                entity = self._evaluate_node(
                    node_key=item.key,
                    parent_key=None,
                    node=item,
                    path=path
                )
                if entity:
                    entities.append(entity)

        elif self.root_pattern == "nested_named_block":
            for outer in getattr(ast, "items", []):
                if not isinstance(outer, AssignmentNode) or not isinstance(outer.value, ObjectNode):
                    continue
                parent_key = outer.key
                for inner in outer.value.items:
                    if not isinstance(inner, AssignmentNode) or not isinstance(inner.value, ObjectNode):
                        continue
                    entity = self._evaluate_node(
                        node_key=inner.key,
                        parent_key=parent_key,
                        node=inner,
                        path=path
                    )
                    if entity:
                        entities.append(entity)

        return entities

    def _evaluate_node(self, node_key: str, parent_key: Optional[str], node: AssignmentNode, path: str) -> Optional[ParsedEntity]:
        entity_id = node_key
        entity_parent_id = parent_key

        source = self.id_rule.get("source")
        if source == "inner_property":
            prop_name = self.id_rule.get("property_name", "id")
            if isinstance(node.value, ObjectNode):
                for child in node.value.items:
                    if isinstance(child, AssignmentNode) and child.key == prop_name:
                        if hasattr(child.value, "value"):
                            entity_id = str(child.value.value)
                        break

        entity = ParsedEntity(
            schema_name=self.schema_name,
            id=entity_id,
            parent_id=entity_parent_id,
            node=node,
            source_path=path,
            properties={},
            case_insensitive_keys=self.case_insensitive_keys
        )

        if isinstance(node.value, ObjectNode):
            for child in node.value.items:
                if isinstance(child, AssignmentNode):
                    entity.properties.setdefault(child.key, []).append(child)

        return entity
