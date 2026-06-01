from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from workscribe.install import (
    disable_codex_hooks_feature_marker,
    ensure_codex_hooks_feature_enabled,
    install_codex_hooks_in_dir,
)


class CodexHooksFeatureConfigTests(unittest.TestCase):
    def test_new_managed_config_uses_hooks_feature(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"

            ensure_codex_hooks_feature_enabled(config_path)

            self.assertIn("[features]\nhooks = true", config_path.read_text())
            self.assertNotIn("codex_hooks", config_path.read_text())

    def test_existing_legacy_codex_hooks_feature_is_migrated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text("[features]\ncodex_hooks = true\n")

            ensure_codex_hooks_feature_enabled(config_path)

            self.assertEqual("[features]\nhooks = true\n", config_path.read_text())

    def test_disable_preserves_unrelated_sections_inside_legacy_marker_range(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "# workscribe-managed codex_hooks:start\n"
                "[features]\n"
                "hooks = true\n"
                "\n"
                "[plugins.example]\n"
                "enabled = true\n"
                "# workscribe-managed codex_hooks:end\n"
            )

            disable_codex_hooks_feature_marker(config_path)

            self.assertEqual("[features]\n\n[plugins.example]\nenabled = true\n", config_path.read_text())

    def test_install_replaces_stale_workscribe_hook_commands(self) -> None:
        with TemporaryDirectory() as temp_dir:
            codex_dir = Path(temp_dir)
            hooks_path = codex_dir / "hooks.json"
            stale_command = (
                'PYTHONPATH="/repo/src" '
                '"/nix/store/stale-python3-3.12.13/bin/python3.12" -m workscribe hook codex'
            )
            hooks_path.write_text(
                "{\n"
                '  "hooks": {\n'
                '    "PostToolUse": [\n'
                '      {"hooks": [{"type": "command", "command": "'
                + stale_command.replace('"', '\\"')
                + '"}]}\n'
                "    ]\n"
                "  }\n"
                "}\n"
            )

            install_codex_hooks_in_dir(codex_dir)

            text = hooks_path.read_text()
            self.assertNotIn(stale_command, text)
            self.assertEqual(text.count("-m workscribe hook codex"), 3)


if __name__ == "__main__":
    unittest.main()
