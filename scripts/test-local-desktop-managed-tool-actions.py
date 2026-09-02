from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_TOOLS = ROOT / "local-engine" / "desktop_tools.py"


class DesktopManagedToolActionBoundaryTests(unittest.TestCase):
    def source_tree(self) -> tuple[str, ast.Module]:
        source = DESKTOP_TOOLS.read_text(encoding="utf-8")
        return source, ast.parse(source, filename=str(DESKTOP_TOOLS))

    def test_desktop_tools_does_not_import_mutating_tool_adapters_directly(self) -> None:
        _source, tree = self.source_tree()
        forbidden_modules = {
            "ffmpeg_online_installer",
            "ffmpeg_update_status",
        }
        forbidden_names = {
            "reset_managed_ffmpeg",
            "seed_managed_ffmpeg",
            "reset_managed_ytdlp",
            "seed_managed_ytdlp",
            "update_managed_ytdlp",
        }
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module in forbidden_modules:
                    violations.append(node.module or "")
                for alias in node.names:
                    if alias.name in forbidden_names:
                        violations.append(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_modules:
                        violations.append(alias.name)
        self.assertEqual(violations, [])

    def test_all_desktop_tool_mutations_use_managed_tool_dispatcher(self) -> None:
        source, tree = self.source_tree()
        imported = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "managed_tool_actions"
            for alias in node.names
        }
        self.assertIn("ManagedToolActionRequest", imported)
        self.assertIn("perform_managed_tool_action", imported)

        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        dispatcher_calls = [
            node
            for node in calls
            if isinstance(node.func, ast.Name) and node.func.id == "perform_managed_tool_action"
        ]
        self.assertGreaterEqual(len(dispatcher_calls), 1)
        self.assertNotIn("install_managed_ffmpeg_online(", source)
        self.assertNotIn("check_ffmpeg_update(", source)
        self.assertNotIn("update_managed_ytdlp(", source)
        self.assertNotIn("reset_managed_ytdlp(", source)
        self.assertNotIn("seed_managed_ffmpeg(", source)
        self.assertNotIn("reset_managed_ffmpeg(", source)

    def test_desktop_requests_explicitly_assert_user_initiation(self) -> None:
        _source, tree = self.source_tree()
        request_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ManagedToolActionRequest"
        ]
        self.assertGreaterEqual(len(request_calls), 1)
        for call in request_calls:
            keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
            value = keywords.get("user_initiated")
            self.assertIsInstance(value, ast.Constant)
            self.assertIs(value.value, True)

    def test_refresh_remains_local_inventory_only(self) -> None:
        source, tree = self.source_tree()
        refresh_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "refresh"
        ]
        self.assertEqual(len(refresh_functions), 1)
        refresh_source = ast.get_source_segment(source, refresh_functions[0]) or ""
        self.assertIn("tool_inventory", refresh_source)
        self.assertNotIn("perform_managed_tool_action", refresh_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
