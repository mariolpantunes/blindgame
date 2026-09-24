import unittest
from dataclasses import replace
from unittest import mock

import numpy as np

from blindgame import reveal
from blindgame.config import parse
from blindgame.game import Game, WrongCode
from blindgame.store import BudgetExhausted, ContestClosed, NotFound, OutOfOrder, Store

CFG = parse(
    {
        "id": "g1",
        "seed": 3,
        "problems": ["Sphere", "Rastrigin"],
        "budget": 5,
        "reveal": {"algorithms": ["Random Search", "Particle Swarm"], "runs": 3, "epochs": 2},
    }
)


def play(game: Game, player, problem: int, n: int | None = None) -> None:
    for k in range(game.spec.budget if n is None else n):
        game.evaluate(player, problem, [0.1 + 0.15 * k, 0.4])


class GameTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.game = Game(self.store, CFG)

    def tearDown(self):
        self.store.close()

    def test_sequential_play_and_reveal(self):
        ana, _ = self.game.join("ana")
        state = self.game.state(ana)
        self.assertEqual((state["attempt"], state["counts"], state["current"]), (1, True, 0))
        self.assertEqual(len(state["problems"]), 1)  # later problems are not listed yet
        with self.assertRaises(OutOfOrder):
            self.game.evaluate(ana, 1, [0.5, 0.5])
        with self.assertRaises(OutOfOrder):
            self.game.reveal(ana, 0)  # budget not spent
        play(self.game, ana, 0)
        with self.assertRaises(BudgetExhausted):
            self.game.evaluate(ana, 0, [0.5, 0.5])

        r = self.game.reveal(ana, 0)
        self.assertEqual(r["landscape"], CFG.spec.landscapes[0])
        self.assertEqual(len(r["you"]["points"]), 5)
        self.assertEqual([m["name"] for m in r["machines"]], ["Random Search", "Particle Swarm"])
        machine = r["machines"][1]
        self.assertEqual(len(machine["start"]), 5)  # OBLESA population = the budget
        self.assertEqual(machine["best"], machine["trail"][-1])
        self.assertGreater(machine["evaluations"], 5)
        self.assertEqual(len(r["field"]["z"]), 128)
        self.assertTrue(0 <= r["machines"][1]["you_beat"] <= 100)
        self.assertEqual(self.game.state(ana)["current"], 1)
        with self.assertRaises(NotFound):
            self.game.reveal(ana, 5)
        with self.assertRaises(NotFound):
            self.game.evaluate(ana, -1, [0.5, 0.5])
        with self.assertRaises(ValueError):
            self.game.evaluate(ana, 1, [2.0, 0.5])

    def test_restart_only_after_finishing(self):
        ana, _ = self.game.join("ana")
        with self.assertRaises(OutOfOrder):
            self.game.restart(ana)
        play(self.game, ana, 0)
        play(self.game, ana, 1)
        self.assertTrue(self.game.state(ana)["finished"])
        first = self.store.attempt(ana)
        second = self.game.restart(ana)
        self.assertNotEqual(first.seed, second.seed)
        state = self.game.state(ana)
        self.assertEqual((state["attempt"], state["counts"], state["current"]), (2, False, 0))

    def test_board_counts_first_attempts_only(self):
        ana, _ = self.game.join("ana")
        rui, _ = self.game.join("rui")
        self.game.join("zé")
        play(self.game, ana, 0)
        play(self.game, rui, 0, n=2)
        board = self.game.board()
        rows = {s["player"]: s for s in board["standings"]}
        self.assertEqual(rows["ana"]["done"], 1)
        self.assertEqual(rows["rui"]["done"], 0)
        self.assertEqual(rows["zé"]["ranks"], [3, 1])  # unplayed ranks last, P2 all tie
        self.assertNotIn("best", str(board))  # no values on the board

        play(self.game, ana, 1)
        self.game.restart(ana)
        play(self.game, ana, 0)  # practice: does not change the board
        self.assertEqual({s["player"]: s["done"] for s in self.game.board()["standings"]}["ana"], 2)

    def test_code_and_closed(self):
        store = Store()
        game = Game(store, replace(CFG, id="g2", code="XYZ"))
        with self.assertRaises(WrongCode):
            game.join("ana", "nope")
        ana, _ = game.join("ana", " xyz ")
        game.cfg = replace(game.cfg, status="closed")
        with self.assertRaises(ContestClosed):
            game.evaluate(ana, 0, [0.5, 0.5])
        with self.assertRaises(ContestClosed):
            game.join("rui", "XYZ")
        store.close()

    def test_first_attempts_share_instances(self):
        ana, _ = self.game.join("ana")
        rui, _ = self.game.join("rui")
        a, r = self.store.attempt(ana), self.store.attempt(rui)
        self.assertNotEqual(a.seed, r.seed)
        np.testing.assert_array_equal(
            self.game.instance(a, 0).x_opt, self.game.instance(r, 0).x_opt
        )
        play(self.game, ana, 0)
        play(self.game, ana, 1)
        practice = self.game.restart(ana)
        self.assertFalse(
            np.allclose(self.game.instance(practice, 0).x_opt, self.game.instance(a, 0).x_opt)
        )

    def test_reveals_precomputed_and_stored(self):
        pending = self.game.precompute()
        self.assertEqual(len(pending), 2)
        for f in pending:
            f.result()
        self.assertEqual(self.game.precompute(), [])  # all in memory now
        # A new server on the same database reads them back instead of recomputing.
        again = Game(self.store, CFG)
        with mock.patch.object(reveal, "compare", side_effect=AssertionError("recomputed")):
            self.assertEqual(again.precompute(), [])
            ana, _ = again.join("ana")
            play(again, ana, 0)
            self.assertEqual(again.reveal(ana, 0)["landscape"], CFG.spec.landscapes[0])

    def test_failed_reveal_is_retried(self):
        ana, _ = self.game.join("ana")
        # Patched before playing: the first evaluation already starts the computation.
        with mock.patch.object(reveal, "compare", side_effect=RuntimeError("boom")):
            play(self.game, ana, 0)
            with self.assertRaises(RuntimeError):
                self.game.reveal(ana, 0)
        self.assertEqual(self.game.reveal(ana, 0)["landscape"], CFG.spec.landscapes[0])

    def test_stop_early(self):
        ana, _ = self.game.join("ana")
        with self.assertRaises(OutOfOrder):
            self.game.stop(ana, 0)  # nothing evaluated yet
        play(self.game, ana, 0, n=2)
        with self.assertRaises(OutOfOrder):
            self.game.stop(ana, 1)  # not the current problem
        self.game.stop(ana, 0)
        state = self.game.state(ana)
        self.assertEqual(state["current"], 1)
        self.assertEqual(len(self.game.reveal(ana, 0)["you"]["points"]), 2)
        with self.assertRaises(BudgetExhausted):
            self.game.evaluate(ana, 0, [0.5, 0.5])  # a stopped problem is over
        with self.assertRaises(BudgetExhausted):
            self.game.stop(ana, 0)
        self.assertEqual(self.game.board()["standings"][0]["done"], 1)
        with self.assertRaises(NotFound):
            self.game.stop(ana, 7)

    def test_cookie_from_another_contest(self):
        other = Game(self.store, replace(CFG, id="g3"))
        _, token = other.join("ana")
        with self.assertRaises(NotFound):
            self.game.player(token)


if __name__ == "__main__":
    unittest.main()
