import unittest

import numpy as np

from blindgame import reveal
from blindgame.problems import make_instance


class RevealTest(unittest.TestCase):
    def test_every_optimizer_runs_from_an_oblesa_start(self):
        ins = make_instance("Rastrigin", 3, 0)
        for name in reveal.ALGORITHMS:
            with self.subTest(name=name):
                r = reveal.run(ins, 6, name, seed=1, epochs=3)
                self.assertEqual(len(r.start), reveal.ALGORITHMS[name].n_pop(6))
                self.assertGreater(r.evaluations, len(r.start))
                self.assertTrue(r.trail)
                # The trail only improves, and ends at the run's best value.
                values = [float(ins(np.array(p))) for p in r.trail]
                self.assertEqual(values, sorted(values, reverse=True))
                self.assertAlmostEqual(values[-1], r.value)
                self.assertTrue(np.all((np.array(r.trail) >= 0) & (np.array(r.trail) <= 1)))

    def test_more_epochs_do_not_hurt(self):
        ins = make_instance("Sphere", 2, 0)
        short = reveal.run(ins, 10, "Particle Swarm", seed=4, epochs=1)
        long = reveal.run(ins, 10, "Particle Swarm", seed=4, epochs=40)
        self.assertLessEqual(long.value, short.value)
        self.assertGreater(long.evaluations, short.evaluations)

    def test_counted_objective(self):
        counted = reveal.Counted(make_instance("Sphere", 0, 0))
        counted(np.full((3, 2), 0.5))
        counted(np.array([1.5, -0.2]))  # clipped into the box, still counted
        self.assertEqual(counted.evaluations, 4)

    def test_compare_is_seeded(self):
        ins = make_instance("Ackley", 5, 1)
        a = reveal.compare(ins, 6, ("Particle Swarm", "Hill Climbing"), 3, 2, seed=9)
        b = reveal.compare(ins, 6, ("Particle Swarm", "Hill Climbing"), 3, 2, seed=9)
        self.assertEqual(a, b)
        self.assertEqual([m["name"] for m in a], ["Particle Swarm", "Hill Climbing"])
        self.assertEqual(len(a[0]["gaps"]), 3)
        self.assertEqual(a[0]["best"], a[0]["trail"][-1])
        self.assertEqual(len(a[0]["start"]), 6)

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
