import os
import unittest

from app.profile_manager import ProfileManager, create_profile_adapter, load_profile_definition
from core.engine import EditCommand, ProjectAnalyzer, TextDiff
from profiles.hoi4.script_parser import AssignmentNode, ComparisonNode, ObjectNode, Parser, TokenKind, Lexer


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def hoi4_profile():
    manager = ProfileManager(os.path.join(ROOT, "profiles"))
    profiles = manager.load_profiles()
    return next(profile for profile in profiles if profile.id == "hoi4")


class ProfileOwnedParserTests(unittest.TestCase):
    def test_hoi4_lexer_preserves_comments_and_trivia(self):
        text = "key = value # comment\r\nnext = 1"
        tokens, diagnostics = Lexer(text).tokenize()

        self.assertFalse(diagnostics)
        self.assertTrue(any(token.kind == TokenKind.COMMENT for token in tokens))
        self.assertTrue(any(token.kind == TokenKind.NEWLINE and token.raw == "\r\n" for token in tokens))
        self.assertEqual(tokens[-1].kind, TokenKind.EOF)

    def test_hoi4_parser_keeps_duplicate_keys_and_comparisons(self):
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
    def test_document_types_are_derived_from_element_configs(self):
        definition = load_profile_definition(hoi4_profile())

        event_rule = next(rule for rule in definition.document_types if rule.id == "event_file")
        decision_rule = next(rule for rule in definition.document_types if rule.id == "decision_file")

        self.assertIn("events/*.txt", event_rule.path_globs)
        self.assertIn("common/decisions/*.txt", decision_rule.path_globs)
        self.assertEqual(definition.classify_document("events/parser_test.txt"), "event_file")

    def test_profile_adapter_extracts_events_children_and_unknown_properties(self):
        adapter = create_profile_adapter(hoi4_profile())
        analyzer = ProjectAnalyzer(adapter)
        event_path = os.path.join(ROOT, "test_mod", "events", "parser_test.txt")
        with open(event_path, "r", encoding="utf-8") as handle:
            document = analyzer.parse_document(event_path, handle.read(), os.path.join(ROOT, "test_mod"))

        self.assertEqual(document.document_type, "event_file")
        self.assertEqual([entity.external_id for entity in document.entities], ["test_parser.1", "test_parser.2"])
        self.assertEqual(len(document.entities[0].children), 2)
        self.assertEqual(len(document.entities[1].children), 1)
        self.assertEqual(document.entities[0].first_property("fire_only_once").type, "bool")
        self.assertTrue(document.entities[0].children[0].first_property("add_political_power").unknown)

    def test_project_index_marks_external_references_without_losing_entities(self):
        adapter = create_profile_adapter(hoi4_profile())
        analyzer = ProjectAnalyzer(adapter)
        event_path = os.path.join(ROOT, "test_mod", "events", "test_events.txt")
        with open(event_path, "r", encoding="utf-8") as handle:
            _, index = analyzer.analyze_project({event_path: handle.read()}, os.path.join(ROOT, "test_mod"))

        self.assertEqual(len(index.entities_by_kind["event"]), 1)
        self.assertTrue(index.references)
        self.assertTrue(all(reference.state == "external_possible" for reference in index.references))

    def test_text_diff_replaces_only_property_value_range(self):
        adapter = create_profile_adapter(hoi4_profile())
        analyzer = ProjectAnalyzer(adapter)
        text = "country_event = { id = old.1 title = old.1.t }"
        document = analyzer.parse_document("events/test.txt", text, "")
        entity = document.entities[0]
        prop = entity.first_property("id")

        command = EditCommand(entity, "id", prop.value, "new.1", prop.range, "Change event id")
        updated = TextDiff.apply_all(text, [TextDiff.for_scalar_property(command)])

        self.assertEqual(updated, "country_event = { id = new.1 title = old.1.t }")

    def test_core_does_not_import_qt_or_profile_parsers(self):
        core_dir = os.path.join(ROOT, "core", "engine")
        forbidden = ("PySide6", "profiles.hoi4", "QUiLoader")
        for dirpath, _, filenames in os.walk(core_dir):
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, "r", encoding="utf-8") as handle:
                    content = handle.read()
                self.assertFalse(any(item in content for item in forbidden), path)


if __name__ == "__main__":
    unittest.main()
