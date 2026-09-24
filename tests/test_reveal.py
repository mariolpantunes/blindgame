import unittest

import numpy as np

from blindgame import reveal
from blindgame.problems import make_instance


class RevealTest(unittest.TestCase):
    def test_every_optimizer_spends_exactly_the_budget(self):
        ins = make_instance("Rastrigin", 3, 0)
        for name in reveal.ALGORITHMS:
            for budget in (5, 17):
                with self.subTest(name=name, budget=budget):
                    run = reveal.run(ins, budget, name, seed=1)
                    self.assertEqual(len(run.values), budget)
                    pts = np.array(run.points)
                    np.testing.assert_allclose(run.values, ins(np.clip(pts, 0, 1)))

    def test_capped_answers_after_budget(self):
        capped = reveal.Capped(make_instance("Sphere", 0, 0), 2)
        out = capped(np.full((3, 2), 0.5))
        self.assertEqual(len(capped.values), 2)
        self.assertEqual(out[2], reveal.EXHAUSTED)
        self.assertEqual(capped(np.array([0.1, 0.1]))[0], reveal.EXHAUSTED)

    def test_compare_is_seeded(self):
        ins = make_instance("Ackley", 5, 1)
        a = reveal.compare(ins, 5, ("Particle Swarm", "Hill Climbing"), 4, seed=9)
        b = reveal.compare(ins, 5, ("Particle Swarm", "Hill Climbing"), 4, seed=9)
        self.assertEqual(a, b)
        self.assertEqual([m["name"] for m in a], ["Particle Swarm", "Hill Climbing"])
        self.assertEqual(len(a[0]["gaps"]), 4)
        self.assertEqual(len(a[0]["path"]), 5)

    def test_percentile(self):
        self.assertEqual(reveal.percentile(1.0, [2.0, 3.0, 0.5, 1.0]), 62.5)
        self.assertEqual(reveal.percentile(1.0, []), 0.0)

    def test_landscape_grid(self):
        ins = make_instance("Levy", 2, 0)
        field = reveal.landscape(ins, resolution=16)
        self.assertEqual(len(field["z"]), 16)
        self.assertLessEqual(field["z_min"], ins.f_opt)
        with self.assertRaises(ValueError):
            reveal.landscape(make_instance("Levy", 2, 0, dim=3))


if __name__ == "__main__":
    unittest.main()
