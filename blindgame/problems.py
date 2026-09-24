"""Hidden problems: pyBlindOpt landscapes behind a seeded, BBOB-style transform.

The player works in the unit box [0, 1]^D. An instance maps a query to the
landscape's native [-5, 5]^D scale through a hidden shift and orthogonal map,
then reports an affinely rescaled value. The player sees neither the function,
nor its optimum, nor f*. Everything is derived from (contest seed, problem index),
so the server can rebuild any instance and never has to store it.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from pyBlindOpt import functions

NATIVE_LO, NATIVE_HI = -5.0, 5.0
# The hidden optimum lies in [MARGIN, 1 - MARGIN]^D of the player's box.
MARGIN = 0.1
# The reported value is scale * (f - f*) + offset: scale log-uniform, offset uniform.
SCALE_RANGE = (0.5, 2.0)
OFFSET_RANGE = (-1000.0, 1000.0)


def _constant(c: float) -> Callable[[int], np.ndarray]:
    return lambda d: np.full(d, c)


def _dixon_price_optimum(d: int) -> np.ndarray:
    i = np.arange(1, d + 1)
    return np.power(2.0, -(np.power(2.0, i) - 2.0) / np.power(2.0, i))


@dataclass(frozen=True)
class Landscape:
    """A pyBlindOpt test function with its known optimum and a one-line description."""

    func: Callable[[np.ndarray], np.ndarray]
    # Native-scale location of a global minimum, for any dimension.
    optimum: Callable[[int], np.ndarray]
    description: str
    # Boundary-penalised landscapes keep axis-aligned walls: signed permutations only.
    rotate: bool = True


LANDSCAPES: dict[str, Landscape] = {
    "Sphere": Landscape(functions.sphere, _constant(0.0), "Unimodal, convex, separable."),
    "Rastrigin": Landscape(
        functions.rastrigin, _constant(0.0), "Highly multimodal, regular grid of local minima."
    ),
    "Ackley": Landscape(
        functions.ackley, _constant(0.0), "Nearly flat outer region, deep central funnel."
    ),
    "Rosenbrock": Landscape(
        functions.rosenbrock,
        _constant(1.0),
        "Narrow curved valley, easy to find, hard to follow.",
    ),
    "Griewank": Landscape(
        functions.griewank, _constant(0.0), "Many shallow local minima on a bowl."
    ),
    "Styblinski-Tang": Landscape(
        functions.styblinski_tang, _constant(-2.903534), "Multimodal, optimum near a corner."
    ),
    "Levy": Landscape(functions.levy, _constant(1.0), "Multimodal with ridged structure."),
    "Zakharov": Landscape(functions.zakharov, _constant(0.0), "Unimodal plate with steep walls."),
    "Dixon-Price": Landscape(
        functions.dixon_price, _dixon_price_optimum, "Valley with symmetric global minima."
    ),
    "Schwefel": Landscape(
        functions.schwefel,
        _constant(4.209687),
        "Deceptive: second-best minima lie far from the global one.",
        rotate=False,
    ),
    "Lunacek": Landscape(
        functions.lunacek_bi_rastrigin,
        _constant(1.25),
        "Double-funnel Rastrigin, the larger funnel is the wrong one.",
        rotate=False,
    ),
}


def random_orthogonal(rng: np.random.Generator, d: int) -> np.ndarray:
    """Haar-distributed orthogonal matrix (QR of a Gaussian, signs fixed)."""
    q, r = np.linalg.qr(rng.standard_normal((d, d)))
    return q * np.sign(np.diag(r))


def signed_permutation(rng: np.random.Generator, d: int) -> np.ndarray:
    """Random permutation matrix with random signs (keeps walls axis-aligned)."""
    return np.eye(d)[rng.permutation(d)] * rng.choice((-1.0, 1.0), size=d)


def to_native(x: np.ndarray) -> np.ndarray:
    """Player box [0, 1] to the native scale [-5, 5], coordinate-wise."""
    return NATIVE_LO + (NATIVE_HI - NATIVE_LO) * np.asarray(x, dtype=float)


@dataclass(frozen=True, eq=False)
class Instance:
    """One hidden problem. Call it on points of the unit box.

    z = o + Q (u - p), where u is the query on the native scale, p the hidden
    optimum on that scale, o the landscape's own optimum and Q orthogonal.
    The reported value is scale * (f(z) - f(o)) + offset, so f* = offset.
    """

    name: str
    dim: int
    x_opt: np.ndarray  # hidden optimum, player coordinates
    transform: np.ndarray  # Q
    scale: float
    offset: float

    @property
    def landscape(self) -> Landscape:
        """The registry entry this instance hides."""
        return LANDSCAPES[self.name]

    @property
    def f_opt(self) -> float:
        """The optimal value as reported to players."""
        return self.offset

    def check(self, x) -> np.ndarray:
        """Validates queries: finite, inside the box, last axis = dim."""
        a = np.asarray(x, dtype=float)
        if a.ndim == 0 or a.shape[-1] != self.dim:
            raise ValueError(f"expected {self.dim} coordinates, got shape {a.shape}")
        if not np.all(np.isfinite(a)):
            raise ValueError("coordinates must be finite")
        if np.any(a < 0.0) or np.any(a > 1.0):
            raise ValueError("coordinates must lie in [0, 1]")
        return a

    def native(self, x) -> np.ndarray:
        """Where a query lands on the landscape's own scale."""
        o = self.landscape.optimum(self.dim)
        return o + (to_native(x) - to_native(self.x_opt)) @ self.transform.T

    def gap(self, value: float) -> float:
        """Distance of a reported value to f*, in the landscape's own units.

        Undoes the hidden scale, so gaps compare across instances. Clipped at 0:
        the optima are known to ~1e-6.
        """
        return max((value - self.offset) / self.scale, 0.0)

    def __call__(self, x) -> np.ndarray:
        """Reported values at points of the unit box (vectorised over the last axis)."""
        a = self.check(x)
        f = self.landscape.func
        raw = f(self.native(a)) - f(self.landscape.optimum(self.dim))
        return self.scale * raw + self.offset


def make_instance(name: str, seed: int, index: int, dim: int = 2) -> Instance:
    """The instance of landscape `name` at position `index` of contest `seed`."""
    if name not in LANDSCAPES:
        raise ValueError(f"unknown landscape '{name}'")
    if seed < 0 or index < 0 or dim < 1:
        raise ValueError("seed and index must be >= 0, dim >= 1")
    rng = np.random.default_rng([seed, index, dim])
    x_opt = rng.uniform(MARGIN, 1.0 - MARGIN, size=dim)
    if LANDSCAPES[name].rotate:
        transform = random_orthogonal(rng, dim)
    else:
        transform = signed_permutation(rng, dim)
    lo, hi = np.log(SCALE_RANGE)
    scale = float(np.exp(rng.uniform(lo, hi)))
    offset = float(rng.uniform(*OFFSET_RANGE))
    return Instance(name, dim, x_opt, transform, scale, offset)


def pick_landscapes(seed: int, n: int) -> tuple[str, ...]:
    """n landscapes for a contest, distinct while possible, in a seeded order."""
    rng = np.random.default_rng([seed])
    names = list(LANDSCAPES)
    picks: list[str] = []
    while len(picks) < n:
        picks += [names[i] for i in rng.permutation(len(names))]
    return tuple(picks[:n])
