import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from blindgame import loadtest, server
from blindgame.store import Store
from tests.test_simulation import LiveServer, free_port


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "game.db"))
        server.BOARD_POLL = 0.02

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_students_play_every_problem(self):
        with LiveServer(self.store, clock=2_000_000.0) as live:
            out = StringIO()
            with redirect_stdout(out):
                code = loadtest.main([live.url, "--students", "4", "--ramp", "0", "--think", "0"])
            board = live.game.board()
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("students finished: 4, errors: 0", out.getvalue())
        self.assertEqual(len(board["standings"]), 4)
        self.assertTrue(all(s["done"] == 3 for s in board["standings"]))

    def test_unreachable_server_is_reported(self):
        report = loadtest.run(f"http://127.0.0.1:{free_port()}", 1, 0, 0, seed=1)
        self.assertEqual(report.finished, 0)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("errors: 1", report.summary())


if __name__ == "__main__":
    unittest.main()
