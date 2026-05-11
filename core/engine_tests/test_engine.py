import os
import unittest

from core.engine import Lexer, Parser, ProfileDefinition, ProjectAnalyzer, TextDiff, EditCommand
from core.engine.ast import AssignmentNode, ComparisonNode, ObjectNode
from core.engine.lexer import TokenKind


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class LexerParserTests(unittest.TestCase):
    def test_lexer_preserves_comments_and_trivia(self):
        text = "key = value # comment\r\nnext = 1"
        tokens, diagnostics = Lexer(text).tokenize()

        self.assertFalse(diagnostics)
        self.assertTrue(any(token.kind == TokenKind.COMMENT for token in tokens))
        self.assertTrue(any(token.kind == TokenKind.NEWLINE and token.raw == "\r\n" for token in tokens))
        self.assertEqual(tokens[-1].kind, TokenKind.EOF)

    def test_parser_keeps_duplicate_keys_and_comparisons(self):
        text = """
country_event = {
    option = { name = a }
    option = { name = b }
    trigger = { stability < 0.5 }
}
"""
        ast, _, diagnostics = Parser(text).parse()
        self.assertFalse(diagnostics)

        event = ast.items[0]
        self.assertIsInstance(event, AssignmentNode)
        self.assertIsInstance(event.value, ObjectNode)
        self.assertEqual(len(event.value.assignments("option")), 2)

        trigger = event.value.first_assignment("trigger")
        self.assertIsNotNone(trigger)
        self.assertIsInstance(trigger.value, ObjectNode)
        self.assertIsInstance(trigger.value.items[0], ComparisonNode)


class ProfileRuntimeTests(unittest.TestCase):
    def test_profile_extracts_events_children_and_unknown_properties(self):
        profile = ProfileDefinition.load(os.path.join(ROOT, "profiles", "hoi4", "profile.json"))
        analyzer = ProjectAnalyzer(profile)
        event_path = os.path.join(ROOT, "test_mod", "events", "parser_test.txt")
        with open(event_path, "r", encoding="utf-8") as handle:
            document = analyzer.parse_document(event_path, handle.read(), os.path.join(ROOT, "test_mod"))

        self.assertEqual(document.document_type, "event_file")
        self.assertEqual([entity.external_id for entity in document.entities], ["test_parser.1", "test_parser.2"])
        self.assertEqual(len(document.entities[0].children), 2)
        self.assertEqual(len(document.entities[1].children), 1)
        self.assertTrue(document.entities[0].first_property("id"))
        self.assertTrue(document.entities[0].first_property("is_triggered_only"))

    def test_project_index_marks_external_references_without_losing_entities(self):
        profile = ProfileDefinition.load(os.path.join(ROOT, "profiles", "hoi4", "profile.json"))
        analyzer = ProjectAnalyzer(profile)
        event_path = os.path.join(ROOT, "test_mod", "events", "test_events.txt")
        with open(event_path, "r", encoding="utf-8") as handle:
            _, index = analyzer.analyze_project({event_path: handle.read()}, os.path.join(ROOT, "test_mod"))

        self.assertEqual(len(index.entities_by_kind["event"]), 1)
        self.assertTrue(index.references)
        self.assertTrue(all(reference.state == "external_possible" for reference in index.references))

    def test_text_diff_replaces_only_property_value_range(self):
        profile = ProfileDefinition.load(os.path.join(ROOT, "profiles", "hoi4", "profile.json"))
        analyzer = ProjectAnalyzer(profile)
        text = "country_event = { id = old.1 title = old.1.t }"
        document = analyzer.parse_document("events/test.txt", text, "")
        entity = document.entities[0]
        prop = entity.first_property("id")

        command = EditCommand(entity, "id", prop.value, "new.1", prop.range, "Change event id")
        updated = TextDiff.apply_all(text, [TextDiff.for_scalar_property(command)])

        self.assertEqual(updated, "country_event = { id = new.1 title = old.1.t }")


if __name__ == "__main__":
    unittest.main()
