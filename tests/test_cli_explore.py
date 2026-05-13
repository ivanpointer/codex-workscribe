from pathlib import Path
from unittest.mock import Mock, patch
import argparse
import unittest

from workscribe import cli


class ExploreCliTests(unittest.TestCase):
    def test_build_parser_parses_explore_options(self) -> None:
        try:
            args = cli.build_parser().parse_args(["explore", "--path", ".", "--port", "8765", "--no-open"])
        except SystemExit as exc:
            self.fail(f"explore command should parse without exiting, exited with {exc.code}")

        self.assertEqual("explore", args.command)
        self.assertEqual(Path("."), args.path)
        self.assertEqual("127.0.0.1", args.host)
        self.assertEqual(8765, args.port)
        self.assertFalse(args.open_browser)

    def test_cmd_explore_discovers_workspace_and_runs_server(self) -> None:
        workspace = Mock()
        args = argparse.Namespace(path=Path("."), host="localhost", port=8765, open_browser=False)

        self.assertTrue(hasattr(cli, "cmd_explore"))

        with (
            patch("workscribe.cli.discover_workspace", return_value=workspace) as discover_workspace,
            patch("workscribe.cli.run_explorer") as run_explorer,
        ):
            exit_code = cli.cmd_explore(args)

        self.assertEqual(0, exit_code)
        discover_workspace.assert_called_once_with(Path(".").resolve())
        run_explorer.assert_called_once_with(workspace, host="localhost", port=8765, open_browser=False)

    def test_cmd_explore_rejects_non_loopback_host(self) -> None:
        args = argparse.Namespace(path=Path("."), host="0.0.0.0", port=8765, open_browser=False)

        with (
            patch("workscribe.cli.discover_workspace") as discover_workspace,
            patch("workscribe.cli.run_explorer") as run_explorer,
        ):
            with self.assertRaisesRegex(cli.WorkscribeError, "local-only"):
                cli.cmd_explore(args)

        discover_workspace.assert_not_called()
        run_explorer.assert_not_called()

    def test_cmd_explore_allows_ipv6_loopback(self) -> None:
        workspace = Mock()
        args = argparse.Namespace(path=Path("."), host="::1", port=8765, open_browser=False)

        with (
            patch("workscribe.cli.discover_workspace", return_value=workspace) as discover_workspace,
            patch("workscribe.cli.run_explorer") as run_explorer,
        ):
            exit_code = cli.cmd_explore(args)

        self.assertEqual(0, exit_code)
        discover_workspace.assert_called_once_with(Path(".").resolve())
        run_explorer.assert_called_once_with(workspace, host="::1", port=8765, open_browser=False)


if __name__ == "__main__":
    unittest.main()
