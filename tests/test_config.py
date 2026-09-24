import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blindgame.config import load, parse

ROOT = Path(__file__).resolve().parent.parent


class ConfigTest(unittest.TestCase):
    def test_example_file_loads(self):
        cfg = load(ROOT / "contest.example.yaml")
        self.assertEqual(cfg.id, "blindgame")
        self.assertEqual(cfg.spec.n_problems, 8)
        self.assertEqual(cfg.spec.budget, 10)
        self.assertEqual((cfg.runs, cfg.epochs), (10, 100))
        self.assertTrue(cfg.is_open)
        self.assertEqual(cfg.code, "")
        self.assertEqual(len(cfg.algorithms), 5)

    def test_defaults_and_list(self):
        cfg = parse({"id": "x", "problems": ["Sphere", "Ackley"], "budget": 7, "code": "ab1"})
        self.assertEqual(sorted(cfg.spec.landscapes), ["Ackley", "Sphere"])
        self.assertEqual(cfg.spec.budget, 7)
        self.assertEqual(cfg.code, "AB1")
        public = cfg.public()
        self.assertTrue(public["needs_code"])
        self.assertNotIn("AB1", str(public))
        self.assertNotIn("Sphere", str(public))

    def test_errors(self):
        for bad in (
            [],
            {"problems": 3},  # no id
            {"id": "bad id!"},
            {"id": "x", "tpyo": 1},
            {"id": "x", "problems": 0},
            {"id": "x", "problems": "many"},
            {"id": "x", "problems": []},
            {"id": "x", "problems": ["Nope"]},
            {"id": "x", "budget": "D/2"},
            {"id": "x", "reveal": {"epochs": 0}},
            {"id": "x", "status": "paused"},
            {"id": "x", "reveal": {"algorithms": ["Nope"]}},
            {"id": "x", "reveal": {"runs": 0}},
            {"id": "x", "reveal": {"extra": 1}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse(bad)

    def test_seed_from_the_clock_unless_pinned(self):
        with mock.patch("blindgame.config.time.time", return_value=1_000_000.0):
            first = parse({"id": "x"})
        with mock.patch("blindgame.config.time.time", return_value=1_000_060.0):
            second = parse({"id": "x"})
        self.assertEqual(first.spec.seed, 1_000_000)
        self.assertNotEqual(first.key, second.key)  # every start is its own contest
        self.assertEqual(parse({"id": "x", "seed": 7}).spec, parse({"id": "x", "seed": 7}).spec)

    def test_listed_functions_are_shuffled_by_the_seed(self):
        names = ["Sphere", "Ackley", "Levy", "Rastrigin", "Griewank", "Zakharov"]
        orders = {
            parse({"id": "x", "seed": s, "problems": names}).spec.landscapes for s in range(8)
        }
        self.assertGreater(len(orders), 1)
        for order in orders:
            self.assertEqual(sorted(order), sorted(names))

    def test_load_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("id: t\nproblems: [Levy]\nstatus: closed\n")
            cfg = load(path)
        self.assertFalse(cfg.is_open)
        self.assertEqual(cfg.spec.landscapes, ("Levy",))


if __name__ == "__main__":
    unittest.main()
