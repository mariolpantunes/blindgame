import unittest

import numpy as np

from blindgame import problems
from blindgame.problems import LANDSCAPES, make_instance, pick_landscapes

GRID = np.stack([a.ravel() for a in np.meshgrid(*[np.linspace(0, 1, 301)] * 2)], axis=-1)


class InstanceTest(unittest.TestCase):
    def test_optimum_is_hidden_point(self):
        """f(x_opt) = f* and no grid point beats it, for every landscape and several seeds."""
        for name in LANDSCAPES:
            for seed in range(5):
                with self.subTest(name=name, seed=seed):
                    ins = make_instance(name, seed, 3)
                    self.assertAlmostEqual(float(ins(ins.x_opt)), ins.f_opt, places=6)
                    self.assertGreaterEqual(float(ins(GRID).min()), ins.f_opt - 1e-9)

    def test_optimum_inside_margin(self):
        for seed in range(50):
            x = make_instance("Sphere", seed, 0).x_opt
            self.assertTrue(np.all(x >= problems.MARGIN) and np.all(x <= 1 - problems.MARGIN))

    def test_deterministic_per_seed_and_index(self):
        a, b = make_instance("Ackley", 7, 2), make_instance("Ackley", 7, 2)
        np.testing.assert_array_equal(a.x_opt, b.x_opt)
        np.testing.assert_array_equal(a.transform, b.transform)
        self.assertEqual((a.scale, a.offset), (b.scale, b.offset))
        c = make_instance("Ackley", 7, 3)
        self.assertFalse(np.allclose(a.x_opt, c.x_opt))

    def test_transform_is_orthogonal(self):
        for name in ("Rastrigin", "Schwefel"):
            q = make_instance(name, 1, 0, dim=5).transform
            np.testing.assert_allclose(q @ q.T, np.eye(5), atol=1e-12)

    def test_penalised_landscapes_stay_axis_aligned(self):
        q = make_instance("Schwefel", 11, 0).transform
        self.assertTrue(np.all(np.isin(q, (-1.0, 0.0, 1.0))))

    def test_output_rescaled(self):
        ins = make_instance("Sphere", 3, 0)
        lo, hi = problems.SCALE_RANGE
        self.assertTrue(lo <= ins.scale <= hi)
        self.assertTrue(problems.OFFSET_RANGE[0] <= ins.f_opt <= problems.OFFSET_RANGE[1])
        # Sphere: f = scale * |z - o|^2 + offset, and |z - o| = |u - p| (orthogonal map).
        x = np.array([0.5, 0.5])
        d2 = np.sum((problems.to_native(x) - problems.to_native(ins.x_opt)) ** 2)
        self.assertAlmostEqual(float(ins(x)), ins.scale * d2 + ins.offset, places=9)

    def test_gap_undoes_scale_and_offset(self):
        ins = make_instance("Sphere", 4, 0)
        self.assertEqual(ins.gap(ins.f_opt), 0.0)
        self.assertEqual(ins.gap(ins.f_opt - 1.0), 0.0)
        self.assertAlmostEqual(ins.gap(ins.f_opt + 3.0 * ins.scale), 3.0)

    def test_vectorised(self):
        ins = make_instance("Levy", 0, 0)
        self.assertEqual(ins(GRID[:10]).shape, (10,))

    def test_dimension_generic(self):
        for d in (1, 3, 10):
            ins = make_instance("Dixon-Price", 2, 0, dim=d)
            self.assertAlmostEqual(float(ins(ins.x_opt)), ins.f_opt, places=6)

    def test_rejects_bad_queries(self):
        ins = make_instance("Sphere", 0, 0)
        for bad in ([0.5], [0.5, 0.5, 0.5], [1.2, 0.5], [-0.1, 0.5], [np.nan, 0.5], 0.5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ins(bad)
        ins([0.0, 1.0])  # the box is closed

    def test_rejects_bad_arguments(self):
        with self.assertRaises(ValueError):
            make_instance("Nope", 0, 0)
        with self.assertRaises(ValueError):
            make_instance("Sphere", -1, 0)


class PickTest(unittest.TestCase):
    def test_distinct_until_exhausted(self):
        picks = pick_landscapes(5, len(LANDSCAPES))
        self.assertEqual(sorted(picks), sorted(LANDSCAPES))
        self.assertEqual(len(pick_landscapes(5, 20)), 20)

    def test_seeded(self):
        self.assertEqual(pick_landscapes(9, 8), pick_landscapes(9, 8))
        self.assertNotEqual(pick_landscapes(9, 8), pick_landscapes(10, 8))


if __name__ == "__main__":
    unittest.main()
