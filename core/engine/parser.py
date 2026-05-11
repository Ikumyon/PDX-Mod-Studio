from __future__ import annotations

from .ast import (
    AssignmentNode,
    AstNode,
    ComparisonNode,
    DocumentAst,
    ErrorNode,
    MissingValueNode,
    ObjectNode,
    ScalarNode,
)
from .lexer import Lexer, Token, TokenKind
from .model import Diagnostic, SourceRange


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
            item = self._parse_statement()
            items.append(item)

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
                return AssignmentNode(
                    SourceRange.between(left.range, value.range),
                    str(left.value),
                    value,
                    left.range,
                    operator.range,
                )
            if self._match(TokenKind.COMPARISON):
                operator = self._previous()
                right = self._parse_value()
                return ComparisonNode(
                    SourceRange.between(left.range, right.range),
                    left,
                    operator.value,
                    right,
                    operator.range,
                )
            return left

        if self._check(TokenKind.LBRACE):
            return self._parse_object()

        bad = self._advance()
        message = f"Unexpected token: {bad.raw!r}"
        node = ErrorNode(bad.range, message, bad.raw)
        self.diagnostics.append(
            Diagnostic("error", message, bad.range, code="unexpected-token", source="parser", target=node)
        )
        return node

    def _parse_value(self) -> AstNode:
        self._skip_trivia()
        if self._check(TokenKind.EOF) or self._check(TokenKind.RBRACE):
            token = self._current()
            node = MissingValueNode(token.range)
            self.diagnostics.append(
                Diagnostic("error", "Missing value", token.range, code="missing-value", source="parser", target=node)
            )
            return node
        if self._check(TokenKind.LBRACE):
            return self._parse_object()
        if self._current().kind in SCALAR:
            return self._parse_scalar()
        bad = self._advance()
        node = ErrorNode(bad.range, f"Invalid value token: {bad.raw!r}", bad.raw)
        self.diagnostics.append(
            Diagnostic("error", node.message, bad.range, code="invalid-value", source="parser", target=node)
        )
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
            self.diagnostics.append(
                Diagnostic("error", "Missing closing brace", end_range, code="missing-closing-brace", source="parser")
            )
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
        self.diagnostics.append(Diagnostic("error", message, token.range, code="expected-token", source="parser"))
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
