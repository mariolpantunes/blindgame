"""The reveal after a problem: the true landscape and pyBlindOpt with the same budget.

Every optimizer is run on the player's own instance through `Capped`, which
records the first `budget` evaluations and answers everything after that with a
huge value. The recorded points are exactly what the optimizer would have
learned with the player's budget, whatever its population or iteration count.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np
import pyBlindOpt as pbo

from .problems import Instance

EXHAUSTED = 1e300


@dataclass(frozen=True)
class Method:
    """How to run one pyBlindOpt optimizer under a tiny budget."""

    cls: type
    min_pop: int = 1
    # Fixed population, e.g. 1 for single-point local search; 0 = sized from the budget.
    pop: int = 0
    # Spend the whole budget in one generation (random search).
    at_once: bool = False

    def n_pop(self, budget: int) -> int:
        """Population size for `budget` evaluations."""
        if self.at_once:
            return budget
        if self.pop:
            return self.pop
        return max(self.min_pop, math.ceil(math.sqrt(budget)))


ALGORITHMS: dict[str, Method] = {
    "Random Search": Method(pbo.RandomSearch, at_once=True),
    "Hill Climbing": Method(pbo.HillClimbing, pop=1),
    "Simulated Annealing": Method(pbo.SimulatedAnnealing, pop=1),
    "Genetic Algorithm": Method(pbo.GeneticAlgorithm, min_pop=2),
    "Differential Evolution": Method(pbo.DifferentialEvolution, min_pop=2),
    "Particle Swarm": Method(pbo.ParticleSwarmOptimization, min_pop=2),
    "Grey Wolf": Method(pbo.GWO, min_pop=4),
    "Enhanced Grey Wolf": Method(pbo.EGWO, min_pop=4),
    "Artificial Bee Colony": Method(pbo.ArtificialBeeColony, min_pop=2),
    "Firefly": Method(pbo.FireflyAlgorithm, min_pop=2),
    "Harris Hawks": Method(pbo.HarrisHawksOptimization, min_pop=2),
    "Cuckoo Search": Method(pbo.CuckooSearch, min_pop=2),
    "Honey Badger": Method(pbo.HoneyBadgerAlgorithm, min_pop=2),
}
DEFAULT_ALGORITHMS = (
    "Random Search",
    "Hill Climbing",
    "Particle Swarm",
    "Differential Evolution",
    "Grey Wolf",
)
DEFAULT_RUNS = 25


class Capped:
    """Objective wrapper: the first `budget` evaluations are real and recorded."""

    def __init__(self, instance: Instance, budget: int):
        """Wrap `instance`, allowing `budget` real evaluations."""
        self.instance = instance
        self.budget = budget
        self.points: list[list[float]] = []
        self.values: list[float] = []

    def __call__(self, x: np.ndarray) -> np.ndarray:
        """Evaluate a point or an (n, D) population; exhausted rows get EXHAUSTED."""
        rows = np.atleast_2d(np.asarray(x, dtype=float))
        out = np.full(len(rows), EXHAUSTED)
        for i, row in enumerate(rows):
            if len(self.values) < self.budget:
                v = float(self.instance(np.clip(row, 0.0, 1.0)))
                self.points.append(row.tolist())
                self.values.append(v)
                out[i] = v
        return out


def run(instance: Instance, budget: int, name: str, seed: int) -> Capped:
    """One run of optimizer `name` limited to `budget` evaluations."""
    method = ALGORITHMS[name]
    n_pop = method.n_pop(budget)
    capped = Capped(instance, budget)
    bounds = np.array([[0.0, 1.0]] * instance.dim)
    # pyBlindOpt logs the vectorisation probe and progress; the reveal needs neither.
    logging.getLogger("pyBlindOpt").setLevel(logging.WARNING)
    opt = method.cls(capped, bounds, n_pop=n_pop, n_iter=math.ceil(budget / n_pop) + 1, seed=seed)
    opt.optimize()
    return capped


def summary(runs: list[Capped], instance: Instance) -> dict:
    """Best gap of each run and their median."""
    gaps = [instance.gap(min(r.values)) for r in runs]
    return {"gaps": gaps, "median_gap": float(np.median(gaps))}


def compare(
    instance: Instance, budget: int, algorithms: tuple[str, ...], n_runs: int, seed: int
) -> list[dict]:
    """Per optimizer: one path to draw, and the best gaps over `n_runs` seeds."""
    out = []
    for name in algorithms:
        runs = [run(instance, budget, name, seed + k) for k in range(n_runs)]
        first = runs[0]
        out.append(
            {
                "name": name,
                "path": [{"x": p, "f": v} for p, v in zip(first.points, first.values, strict=True)],
                **summary(runs, instance),
            }
        )
    return out


def percentile(gap: float, gaps: list[float]) -> float:
    """Share of runs the player beat (ties count half), in [0, 100]."""
    if not gaps:
        return 0.0
    beaten = sum(1.0 if g > gap else 0.5 if g == gap else 0.0 for g in gaps)
    return 100.0 * beaten / len(gaps)


def landscape(instance: Instance, resolution: int = 128) -> dict:
    """Reported values on a grid of the unit square (2D only); row j is y[j]."""
    if instance.dim != 2:
        raise ValueError("the colour map exists for 2D problems only")
    axis = np.linspace(0.0, 1.0, resolution)
    xs, ys = np.meshgrid(axis, axis)
    z = instance(np.stack((xs.ravel(), ys.ravel()), axis=-1)).reshape(xs.shape)
    return {
        "resolution": resolution,
        "z": np.round(z, 6).tolist(),
        "z_min": min(float(z.min()), instance.f_opt),
        "z_max": float(z.max()),
    }
