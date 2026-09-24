"""The reveal after a problem: the true landscape and pyBlindOpt as the reference.

Each optimizer starts from an OBLESA population as large as the player's budget
and runs for a fixed number of epochs on the player's own instance: the
"solution" a machine finds with far more evaluations than the player had. One
run is kept for drawing (initial population, best-so-far trail, final best);
more seeds give the distribution the player is compared with.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pyBlindOpt as pbo
from pyBlindOpt import init, utils

from .problems import Instance


@dataclass(frozen=True)
class Method:
    """A pyBlindOpt optimizer and the smallest population it accepts."""

    cls: type
    min_pop: int = 1

    def n_pop(self, budget: int) -> int:
        """Population size: the player's budget, or the optimizer's minimum."""
        return max(self.min_pop, budget)


ALGORITHMS: dict[str, Method] = {
    "Random Search": Method(pbo.RandomSearch),
    "Hill Climbing": Method(pbo.HillClimbing),
    "Simulated Annealing": Method(pbo.SimulatedAnnealing),
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
DEFAULT_RUNS = 10
DEFAULT_EPOCHS = 100


class Counted:
    """Objective wrapper that counts evaluations (points, not calls)."""

    def __init__(self, instance: Instance):
        """Wrap `instance` with a zero count."""
        self.instance = instance
        self.evaluations = 0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        """Evaluate a point or an (n, D) population, clipped to the box."""
        rows = np.atleast_2d(np.asarray(x, dtype=float))
        self.evaluations += len(rows)
        return self.instance(np.clip(rows, 0.0, 1.0))


@dataclass
class Run:
    """One optimizer run: what to draw and how good it was."""

    start: list[list[float]]  # the OBLESA initial population
    trail: list[list[float]] = field(default_factory=list)  # best-so-far, at each improvement
    value: float = float("inf")  # best reported value
    evaluations: int = 0

    def improve(self, population: np.ndarray, scores: np.ndarray) -> None:
        """Extend the trail if this generation holds a new best."""
        i = int(np.argmin(scores))
        if float(scores[i]) < self.value:
            self.value = float(scores[i])
            self.trail.append(np.clip(population[i], 0.0, 1.0).tolist())


def run(instance: Instance, budget: int, name: str, seed: int, epochs: int) -> Run:
    """One run of optimizer `name`: OBLESA start of `budget` points, then `epochs` epochs."""
    method = ALGORITHMS[name]
    n_pop = method.n_pop(budget)
    bounds = np.array([[0.0, 1.0]] * instance.dim)
    rng = np.random.default_rng(seed)
    objective = Counted(instance)
    # pyBlindOpt logs the vectorisation probe and progress; the reveal needs neither.
    logging.getLogger("pyBlindOpt").setLevel(logging.WARNING)
    start = np.asarray(
        init.oblesa(objective, bounds, population=utils.RandomSampler(rng), n_pop=n_pop, seed=rng)
    )
    result = Run(start=np.clip(start, 0.0, 1.0).tolist())
    result.improve(start, instance(np.clip(start, 0.0, 1.0)))

    def track(_epoch: int, scores: np.ndarray, population: np.ndarray) -> bool:
        result.improve(np.asarray(population), np.asarray(scores))
        return False

    opt = method.cls(
        objective, bounds, population=start, n_pop=n_pop, n_iter=epochs, seed=rng, callback=track
    )
    best_pos, best_value = opt.optimize()[:2]
    result.improve(np.atleast_2d(best_pos), np.atleast_1d(best_value))
    result.evaluations = objective.evaluations
    return result


def compare(
    instance: Instance,
    budget: int,
    algorithms: tuple[str, ...],
    n_runs: int,
    epochs: int,
    seed: int,
) -> list[dict]:
    """Per optimizer: the first run to draw, and the best gaps over `n_runs` seeds."""
    out = []
    for name in algorithms:
        runs = [run(instance, budget, name, seed + k, epochs) for k in range(n_runs)]
        gaps = [instance.gap(r.value) for r in runs]
        first = runs[0]
        out.append(
            {
                "name": name,
                "start": first.start,
                "trail": first.trail,
                "best": first.trail[-1],
                "evaluations": first.evaluations,
                "gaps": gaps,
                "median_gap": float(np.median(gaps)),
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
