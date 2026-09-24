import os
import tempfile
import unittest
from pathlib import Path

from blindgame.config import load, parse

ROOT = Path(__file__).resolve().parent.parent


class ConfigTest(unittest.TestCase):
    def test_example_file_loads(self):
        cfg = load(ROOT / "contest.example.yaml")
        self.assertEqual(cfg.id, "faa-2026-class-02")
        self.assertEqual(cfg.spec.n_problems, 8)
        self.assertEqual(cfg.spec.budget, 5)
        self.assertTrue(cfg.is_open)
        self.assertEqual(cfg.code, "")
        self.assertEqual(len(cfg.algorithms), 5)

    def test_defaults_and_list(self):
        cfg = parse({"id": "x", "problems": ["Sphere", "Ackley"], "budget": 7, "code": "ab1"})
        self.assertEqual(cfg.spec.landscapes, ("Sphere", "Ackley"))
        self.assertEqual(cfg.spec.budget, 7)
        self.assertEqual(cfg.code, "AB1")
        self.assertEqual(cfg.title, "x")
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
            {"id": "x", "problems": ["Nope"]},
            {"id": "x", "budget": "D^3"},
            {"id": "x", "status": "paused"},
            {"id": "x", "reveal": {"algorithms": ["Nope"]}},
            {"id": "x", "reveal": {"runs": 0}},
            {"id": "x", "reveal": {"extra": 1}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse(bad)

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
