import unittest

from blindgame.contest import (
    ContestSpec,
    Result,
    budget_for,
    leaderboard,
    precision,
    rank_problem,
)


class SpecTest(unittest.TestCase):
    def test_budget_formulas(self):
        for rule, d, expected in (
            ("4D+D", 2, 10),
            ("4D+D", 10, 50),
            ("3D+D", 2, 8),
            ("3*D + D", 2, 8),
            ("D^2+1", 10, 101),
            ("2^D+1", 10, 1025),
            ("(D+1)^2", 2, 9),
            ("12", 3, 12),
        ):
            with self.subTest(rule=rule, d=d):
                self.assertEqual(budget_for(rule, d), expected)
        for bad in ("0", "", "-1", "x", "D**", "1e3", "D^100", "__import__('os')", "2/D"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                budget_for(bad, 2)
        self.assertEqual(ContestSpec(1, ("Sphere",)).budget, 10)  # default 4D+D
        self.assertEqual(ContestSpec(1, ("Sphere",), dim=3).budget, 15)

    def test_random_contest(self):
        spec = ContestSpec.random(42)
        self.assertEqual(spec.n_problems, 8)
        instances = spec.instances(7)
        self.assertEqual(len(instances), 8)
        self.assertEqual(instances[3].name, spec.landscapes[3])

    def test_attempts_get_their_own_instances(self):
        spec = ContestSpec.random(42, n_problems=2)
        a, b = spec.instances(1), spec.instances(2)
        self.assertEqual([i.name for i in a], [i.name for i in b])
        self.assertFalse((a[0].x_opt == b[0].x_opt).all())

    def test_roundtrip(self):
        spec = ContestSpec.random(3, n_problems=4)
        self.assertEqual(ContestSpec.from_dict(spec.to_dict()), spec)

    def test_validation(self):
        for kwargs in (
            {"seed": -1, "landscapes": ("Sphere",)},
            {"seed": 0, "landscapes": ()},
            {"seed": 0, "landscapes": ("Nope",)},
            {"seed": 0, "landscapes": ("Sphere",), "dim": 0},
            {"seed": 0, "landscapes": ("Sphere",), "budget_rule": "x"},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                ContestSpec(**kwargs)


class ScoringTest(unittest.TestCase):
    def test_competition_ranking(self):
        ranks = rank_problem(
            [
                Result("a", 1.0, 3),
                Result("b", 0.5, 5),
                Result("c", 1.0, 3),
                Result("d", 1.0, 2),
                Result("e", None),
            ]
        )
        self.assertEqual(ranks, {"b": 1, "d": 2, "a": 3, "c": 3, "e": 5})

    def test_leaderboard_sums_ranks(self):
        per_problem = [
            [Result("ana", 0.1, 1), Result("rui", 0.2, 1)],
            [Result("rui", -5.0, 4)],  # ana never played problem 1
        ]
        board = leaderboard(per_problem, ["ana", "rui", "zé"])
        self.assertEqual(
            [(s.player, s.total, s.ranks) for s in board],
            [
                ("ana", 3, (1, 2)),
                ("rui", 3, (2, 1)),
                ("zé", 5, (3, 2)),
            ],
        )

    def test_precision(self):
        self.assertAlmostEqual(precision(0.001), -3.0)
        self.assertEqual(precision(0.0), -8.0)


if __name__ == "__main__":
    unittest.main()
