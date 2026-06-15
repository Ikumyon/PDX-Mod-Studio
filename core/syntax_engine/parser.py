from __future__ import annotations

from .models import AssignmentNode, ChildrenNode, CommentNode, FileNode, SyntaxDefinition, Token, ValueNode


class GenericTextParser:
    def __init__(self, syntax: SyntaxDefinition):
        self.syntax = syntax
        self._comparison_operators = set(syntax.comparison_operators)

    def parse(self, text: str) -> FileNode:
        tokens = self._tokenize(text)
        parser = _TokenParser(tokens, self.syntax, self._comparison_operators)
        return parser.parse_file()

    def _tokenize(self, text: str) -> list[Token]:
        tokens: list[Token] = []
        index = 0
        line = 1
        column = 1
        assignment = self.syntax.assignment
        block_open = self.syntax.block_open
        block_close = self.syntax.block_close
        comment = self.syntax.comment
        quotes = self.syntax.string_quotes
        escape = self.syntax.escape
        children_by = self.syntax.children_by

        indent_stack = [0]
        at_line_start = True

        while index < len(text):
            if children_by == "indent" and at_line_start:
                temp_idx = index
                temp_col = column
                indent_spaces = 0
                while temp_idx < len(text) and text[temp_idx] in " \t":
                    indent_spaces += 1 if text[temp_idx] == " " else 4
                    temp_idx += 1
                    temp_col += 1

                is_empty_or_comment = False
                if temp_idx >= len(text):
                    is_empty_or_comment = True
                elif text[temp_idx] in "\r\n":
                    is_empty_or_comment = True
                elif text.startswith(comment, temp_idx):
                    is_empty_or_comment = True

                if not is_empty_or_comment:
                    current_indent = indent_stack[-1]
                    if indent_spaces > current_indent:
                        tokens.append(Token("INDENT", " " * (indent_spaces - current_indent), line, column))
                        indent_stack.append(indent_spaces)
                    elif indent_spaces < current_indent:
                        while indent_spaces < indent_stack[-1]:
                            tokens.append(Token("DEDENT", "", line, column))
                            indent_stack.pop()
                        if indent_spaces != indent_stack[-1]:
                            raise ValueError(f"Inconsistent indentation at line {line}, column {column}")
                    index = temp_idx
                    column = temp_col

                at_line_start = False
                if index >= len(text):
                    break

            current = text[index]

            if current == "\r":
                index += 1
                continue

            if current == "\n":
                tokens.append(Token("NEWLINE", "\n", line, column))
                index += 1
                line += 1
                column = 1
                at_line_start = True
                continue

            if current.isspace():
                index += 1
                column += 1
                continue

            if text.startswith(comment, index):
                start_column = column
                index += len(comment)
                column += len(comment)
                start = index
                while index < len(text) and text[index] not in "\r\n":
                    index += 1
                    column += 1
                tokens.append(Token("COMMENT", text[start:index], line, start_column))
                continue

            if children_by == "bracket":
                if text.startswith(block_open, index):
                    tokens.append(Token("BLOCK_OPEN", block_open, line, column))
                    index += len(block_open)
                    column += len(block_open)
                    continue

                if text.startswith(block_close, index):
                    tokens.append(Token("BLOCK_CLOSE", block_close, line, column))
                    index += len(block_close)
                    column += len(block_close)
                    continue

            if text.startswith(assignment, index):
                tokens.append(Token("ASSIGN", assignment, line, column))
                index += len(assignment)
                column += len(assignment)
                continue

            if current in ("<", ">", "!"):
                start = index
                start_column = column
                index += 1
                column += 1
                if index < len(text) and text[index] == "=":
                    index += 1
                    column += 1
                tokens.append(Token("OP", text[start:index], line, start_column))
                continue

            if current in quotes:
                start_column = column
                index += 1
                column += 1
                value_parts: list[str] = []
                while index < len(text):
                    char = text[index]
                    if char == "\r":
                        index += 1
                        continue
                    if char == "\n":
                        raise ValueError(f"Unterminated string at line {line}, column {start_column}")
                    if char == escape and index + 1 < len(text):
                        value_parts.append(text[index + 1])
                        index += 2
                        column += 2
                        continue
                    if char == current:
                        index += 1
                        column += 1
                        break
                    value_parts.append(char)
                    index += 1
                    column += 1
                else:
                    raise ValueError(f"Unterminated string at line {line}, column {start_column}")
                tokens.append(Token("STRING", current + "".join(value_parts) + current, line, start_column))
                continue

            start = index
            start_column = column
            stop_chars = {
                "\r",
                "\n",
                " ",
                "\t",
                "<",
                ">",
                "!",
            } | set(quotes)
            while index < len(text):
                if text.startswith(comment, index):
                    break
                if children_by == "bracket" and (text.startswith(block_open, index) or text.startswith(block_close, index)):
                    break
                if text.startswith(assignment, index):
                    break
                if text[index] in stop_chars:
                    break
                index += 1
                column += 1
            tokens.append(Token("WORD", text[start:index], line, start_column))

        if children_by == "indent":
            while len(indent_stack) > 1:
                tokens.append(Token("DEDENT", "", line, column))
                indent_stack.pop()

        tokens.append(Token("EOF", "", line, column))
        return tokens


class _TokenParser:
    def __init__(self, tokens: list[Token], syntax: SyntaxDefinition, comparison_operators: set[str]):
        self.tokens = tokens
        self.syntax = syntax
        self.comparison_operators = comparison_operators
        self.index = 0

    def parse_file(self) -> FileNode:
        return FileNode(kind="file", children=self._parse_children(end_kind="EOF"))

    def _parse_children(self, end_kind: str) -> list[object]:
        children: list[object] = []
        while self.current.kind != end_kind:
            if self.current.kind == "EOF":
                raise ValueError(f"Unexpected end of file while waiting for {end_kind}")
            if self.current.kind == "NEWLINE":
                self.index += 1
                continue
            if self.current.kind == "COMMENT":
                children.append(
                    CommentNode(
                        kind="comment",
                        value=self.current.value,
                        line=self.current.line,
                        column=self.current.column,
                        length=max(1, len(self.current.value)),
                    )
                )
                self.index += 1
                continue
            if self.current.kind == "BLOCK_CLOSE" and end_kind != "BLOCK_CLOSE":
                raise ValueError(f"Unexpected block close at line {self.current.line}, column {self.current.column}")
            if self.current.kind == "DEDENT" and end_kind != "DEDENT":
                raise ValueError(f"Unexpected dedent at line {self.current.line}, column {self.current.column}")
            children.append(self._parse_statement(end_kind))
        if end_kind in {"BLOCK_CLOSE", "DEDENT"}:
            self.index += 1
        return children

    def _parse_statement(self, end_kind: str) -> AssignmentNode | ValueNode:
        current = self.current
        if current.kind not in {"WORD", "STRING"}:
            raise ValueError(f"Unexpected token {current.kind} at line {current.line}, column {current.column}")

        next_significant = self._peek_significant()
        if next_significant.kind == "ASSIGN":
            return self._parse_assignment()

        if (
            next_significant.kind == "OP"
            and next_significant.value in self.comparison_operators
        ):
            return self._parse_expression_value(end_kind)

        self.index += 1
        return ValueNode(
            kind="value",
            value=current.value,
            line=current.line,
            column=current.column,
            length=max(1, len(current.value)),
        )

    def _parse_assignment(self) -> AssignmentNode:
        left_token = self.current
        left = left_token.value
        self.index += 1
        operator = self._expect("ASSIGN").value
        
        if self.syntax.children_by == "bracket" and self.current.kind == "BLOCK_OPEN":
            open_token = self.current
            self.index += 1
            right = ChildrenNode(
                kind="children",
                children=self._parse_children(end_kind="BLOCK_CLOSE"),
                line=open_token.line,
                column=open_token.column,
                length=max(1, len(open_token.value)),
            )
        elif self.syntax.children_by == "indent" and self._peek_is_indent():
            while self.current.kind in {"NEWLINE", "COMMENT"}:
                self.index += 1
            indent_token = self.current
            self.index += 1
            right = ChildrenNode(
                kind="children",
                children=self._parse_children(end_kind="DEDENT"),
                line=indent_token.line,
                column=indent_token.column,
                length=1,
            )
        else:
            right = self._parse_assignment_value()

        return AssignmentNode(
            kind="assignment",
            left=left,
            operator=operator,
            right=right,
            line=left_token.line,
            column=left_token.column,
            length=max(1, len(left)),
        )

    def _parse_assignment_value(self) -> ValueNode:
        token = self.current
        if token.kind not in {"WORD", "STRING"}:
            raise ValueError(f"Expected value at line {token.line}, column {token.column}")
        self.index += 1
        return ValueNode(
            kind="value",
            value=token.value,
            line=token.line,
            column=token.column,
            length=max(1, len(token.value)),
        )

    def _parse_expression_value(self, end_kind: str) -> ValueNode:
        start_token = self.current
        parts: list[str] = []
        while self.current.kind not in {"NEWLINE", "COMMENT", "EOF", end_kind}:
            token = self.current
            if token.kind in {"BLOCK_CLOSE", "DEDENT"}:
                break
            parts.append(token.value)
            self.index += 1
        value = " ".join(parts)
        return ValueNode(
            kind="value",
            value=value,
            line=start_token.line,
            column=start_token.column,
            length=max(1, len(value)),
        )

    def _peek_significant(self) -> Token:
        index = self.index + 1
        while index < len(self.tokens):
            token = self.tokens[index]
            if token.kind not in {"NEWLINE", "COMMENT"}:
                return token
            index += 1
        return self.tokens[-1]

    def _peek_is_indent(self) -> bool:
        index = self.index
        while index < len(self.tokens):
            token = self.tokens[index]
            if token.kind == "INDENT":
                return True
            if token.kind not in {"NEWLINE", "COMMENT"}:
                return False
            index += 1
        return False

    def _expect(self, kind: str) -> Token:
        token = self.current
        if token.kind != kind:
            raise ValueError(f"Expected {kind}, got {token.kind} at line {token.line}, column {token.column}")
        self.index += 1
        return token

    @property
    def current(self) -> Token:
        return self.tokens[self.index]
