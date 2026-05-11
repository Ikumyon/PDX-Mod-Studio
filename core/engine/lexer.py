from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import Diagnostic, SourcePosition, SourceRange


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


class Lexer:
    """Loss-preserving lexer for Paradox-style key/value scripts."""

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
                        source="lexer",
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
        if index >= len(self.text):
            return ""
        return self.text[index]

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
            Diagnostic(
                severity="error",
                message="Unterminated string literal",
                range=token.range,
                code="unterminated-string",
                source="lexer",
            )
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
        if ch.isdigit():
            return True
        return ch in "+-" and self._peek(1).isdigit()

    def _starts_comparison(self) -> bool:
        return any(self.text.startswith(op, self.offset) for op in self.COMPARISON_OPERATORS)

    def _starts_identifier(self, ch: str) -> bool:
        return ch.isalpha() or ch == "_" or ch == "."

    def _is_identifier_char(self, ch: str) -> bool:
        return ch.isalnum() or ch in "_.:/@$%+-"
