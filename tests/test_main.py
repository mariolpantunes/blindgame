import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blindgame import __main__ as cli

EXAMPLE = Path(__file__).resolve().parent.parent / "contest.example.yaml"


class MainTest(unittest.TestCase):
    def run_cli(self, *args: str) -> mock.MagicMock:
        with (
            mock.patch.object(sys, "argv", ["blindgame", *args]),
            mock.patch.object(cli.uvicorn, "run") as run,
            mock.patch("builtins.print"),
        ):
            cli.main()
        return run

    def test_serves_the_contest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "g.db")
            run = self.run_cli("--config", str(EXAMPLE), "--db", db, "--port", "8123")
            self.assertEqual(run.call_args.kwargs["port"], 8123)
            self.assertEqual(run.call_args.kwargs["forwarded_allow_ips"], "127.0.0.1")
            self.assertTrue(os.path.exists(db))

    def test_bad_config_exits_with_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.yaml")
            Path(bad).write_text("title: no id\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as stop:
                self.run_cli("--config", bad, "--db", os.path.join(tmp, "g.db"))
            self.assertIn("id is required", str(stop.exception.code))

    def test_changed_setup_needs_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "g.db")
            first = os.path.join(tmp, "a.yaml")
            second = os.path.join(tmp, "b.yaml")
            Path(first).write_text("id: same\nseed: 1\n", encoding="utf-8")
            Path(second).write_text("id: same\nseed: 2\n", encoding="utf-8")
            self.run_cli("--config", first, "--db", db)
            with self.assertRaises(SystemExit) as stop:
                self.run_cli("--config", second, "--db", db)
            self.assertIn("--reset", str(stop.exception.code))
            self.run_cli("--config", second, "--db", db, "--reset")


if __name__ == "__main__":
    unittest.main()
