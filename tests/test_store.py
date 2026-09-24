import os
import tempfile
import threading
import unittest

from blindgame.contest import ContestSpec
from blindgame.store import BudgetExhausted, Conflict, NotFound, OutOfOrder, Store

SPEC = ContestSpec.random(1, n_problems=3)
B = SPEC.budget


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.store.ensure_contest("c1", SPEC)

    def tearDown(self):
        self.store.close()

    def test_ensure_contest_guards_the_spec(self):
        self.store.ensure_contest("c1", SPEC)  # same spec: fine
        other = ContestSpec.random(2, n_problems=3)
        with self.assertRaises(Conflict):
            self.store.ensure_contest("c1", other)
        player, _ = self.store.join("c1", "ana")
        self.store.record(self.store.attempt(player), 0, [0.5, 0.5], 1.0, B)
        self.store.ensure_contest("c1", other, reset=True)  # wipes the results
        self.assertEqual(self.store.players("c1"), [])

    def test_join_and_token(self):
        player, token = self.store.join("c1", "  Ana   Silva ")
        self.assertEqual(player.nickname, "Ana Silva")
        self.assertEqual(self.store.player(token), player)
        with self.assertRaises(Conflict):
            self.store.join("c1", "Ana Silva")
        with self.assertRaises(ValueError):
            self.store.join("c1", "   ")
        with self.assertRaises(NotFound):
            self.store.player("forged")
        self.assertEqual(self.store.players("c1"), [player])

    def test_attempts(self):
        player, _ = self.store.join("c1", "ana")
        first = self.store.attempt(player)  # created on first use
        self.assertEqual(first.number, 1)
        self.assertEqual(self.store.attempt(player), first)
        second = self.store.new_attempt(player)
        self.assertEqual(second.number, 2)
        self.assertNotEqual(first.seed, second.seed)
        self.assertEqual(self.store.attempt(player), second)
        self.assertEqual(self.store.first_attempts("c1"), [(player, first)])

    def test_budget_and_order(self):
        player, _ = self.store.join("c1", "ana")
        att = self.store.attempt(player)
        with self.assertRaises(OutOfOrder):
            self.store.record(att, 1, [0.5, 0.5], 1.0, B)
        for i in range(B):
            q = self.store.record(att, 0, [0.1 * i, 0.5], 10.0 - i, B)
            self.assertEqual(q.seq, i + 1)
        with self.assertRaises(BudgetExhausted):
            self.store.record(att, 0, [0.5, 0.5], 0.0, B)
        self.store.record(att, 1, [0.5, 0.5], 1.0, B)
        self.assertEqual(len(self.store.history(att, 0)), B)
        self.assertEqual(len(self.store.history(att)), B + 1)

    def test_budget_under_concurrency(self):
        player, _ = self.store.join("c1", "ana")
        att = self.store.attempt(player)
        errors: list[Exception] = []

        def hit():
            try:
                self.store.record(att, 0, [0.5, 0.5], 1.0, B)
            except BudgetExhausted as e:
                errors.append(e)

        threads = [threading.Thread(target=hit) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self.store.history(att, 0)), B)
        self.assertEqual(len(errors), 20 - B)

    def test_bests_first_hit_and_spent(self):
        ana, _ = self.store.join("c1", "ana")
        att = self.store.attempt(ana)
        for f in (5.0, 2.0, 3.0, 2.0):
            self.store.record(att, 0, [0.5, 0.5], f, B)
        [best] = self.store.bests([att.id])
        self.assertEqual((best.problem, best.best, best.used, best.spent), (0, 2.0, 2, 4))
        self.assertEqual(self.store.bests([]), [])

    def test_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "game.db")
            store = Store(path)
            store.ensure_contest("c2", SPEC)
            player, token = store.join("c2", "ana")
            store.record(store.attempt(player), 0, [0.25, 0.75], 3.5, B)
            store.close()
            store = Store(path)
            att = store.attempt(store.player(token))
            self.assertEqual(store.history(att)[0].x, (0.25, 0.75))
            store.close()


if __name__ == "__main__":
    unittest.main()
