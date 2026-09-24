"""Contest definition and BBComp-style scoring.

A contest is a seed plus an ordered list of landscapes. Every attempt plays its
own hidden instances of those landscapes (same functions, own shift, rotation and
scale), so a revealed answer is useless to anyone else. Players are ranked per
problem by the gap to the optimum in the landscape's own units (ties: whoever
reached their best in fewer evaluations); the score is the sum of ranks (lower
is better).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from . import problems

DEFAULT_PROBLEMS = 8
DEFAULT_DIM = 2

# Evaluations per problem as a function of the dimension. All give 5 in 2D.
BUDGET_RULES = {
    "2D+1": lambda d: 2 * d + 1,
    "D^2+1": lambda d: d * d + 1,
    "2^D+1": lambda d: 2**d + 1,
}
DEFAULT_BUDGET_RULE = "D^2+1"


def budget_for(rule: str, dim: int) -> int:
    """A rule name from BUDGET_RULES, or a positive integer as text."""
    if rule in BUDGET_RULES:
        return BUDGET_RULES[rule](dim)
    if rule.isdigit() and int(rule) > 0:
        return int(rule)
    raise ValueError(f"budget must be one of {list(BUDGET_RULES)} or a positive integer")


@dataclass(frozen=True)
class ContestSpec:
    """The game itself: seed, ordered landscapes, dimension and budget rule.

    Two specs are equal exactly when they define the same game, which is what
    the store checks before reusing a contest id.
    """

    seed: int
    landscapes: tuple[str, ...]
    dim: int = DEFAULT_DIM
    budget_rule: str = DEFAULT_BUDGET_RULE

    def __post_init__(self):
        """Reject impossible specs early, with a message for the contest file."""
        if self.seed < 0:
            raise ValueError("seed must be >= 0")
        if not self.landscapes:
            raise ValueError("a contest needs at least one problem")
        unknown = [n for n in self.landscapes if n not in problems.LANDSCAPES]
        if unknown:
            raise ValueError(f"unknown landscapes {unknown}")
        if self.dim < 1:
            raise ValueError("dim must be >= 1")
        budget_for(self.budget_rule, self.dim)  # validates the rule

    @classmethod
    def random(
        cls,
        seed: int,
        n_problems: int = DEFAULT_PROBLEMS,
        dim: int = DEFAULT_DIM,
        budget_rule: str = DEFAULT_BUDGET_RULE,
    ) -> "ContestSpec":
        """A spec with `n_problems` landscapes picked (seeded) from the registry."""
        return cls(seed, problems.pick_landscapes(seed, n_problems), dim, budget_rule)

    @property
    def budget(self) -> int:
        """Evaluations per problem under this spec's rule."""
        return budget_for(self.budget_rule, self.dim)

    @property
    def n_problems(self) -> int:
        """Number of problems in the sequence."""
        return len(self.landscapes)

    def instances(self, attempt_seed: int) -> tuple[problems.Instance, ...]:
        """The hidden problems of one attempt."""
        return tuple(
            problems.make_instance(name, attempt_seed, i, self.dim)
            for i, name in enumerate(self.landscapes)
        )

    def to_dict(self) -> dict:
        """JSON-ready form, as stored in the database."""
        return {
            "seed": self.seed,
            "landscapes": list(self.landscapes),
            "dim": self.dim,
            "budget_rule": self.budget_rule,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContestSpec":
        """Inverse of `to_dict`."""
        return cls(int(d["seed"]), tuple(d["landscapes"]), int(d["dim"]), str(d["budget_rule"]))

    def public(self) -> dict:
        """What players may know: the size of the box, never the landscapes."""
        return {
            "dim": self.dim,
            "budget": self.budget,
            "bounds": [[0.0, 1.0]] * self.dim,
            "problems": self.n_problems,
        }


# --- Scoring ------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    """One player's outcome on one problem."""

    player: str
    gap: float | None  # to f*, in the landscape's units; None: not played
    used: int = 0  # evaluations it took to reach the best value


def rank_problem(results: Sequence[Result]) -> dict[str, int]:
    """Standard competition ranking (1, 2, 2, 4) on (gap, used).

    Players without an evaluation share the last place.
    """
    played = sorted(
        ((r.gap, r.used, r.player) for r in results if r.gap is not None),
        key=lambda t: (t[0], t[1]),
    )
    ranks: dict[str, int] = {}
    prev: tuple[float, int] | None = None
    rank = 0
    for pos, (gap, used, player) in enumerate(played, start=1):
        if (gap, used) != prev:
            rank, prev = pos, (gap, used)
        ranks[player] = rank
    for r in results:
        ranks.setdefault(r.player, len(played) + 1)
    return ranks


@dataclass(frozen=True)
class Standing:
    """One player's line on the leaderboard: rank sum and per-problem ranks."""

    player: str
    total: int
    ranks: tuple[int, ...]


def leaderboard(per_problem: Sequence[Sequence[Result]], players: Sequence[str]) -> list[Standing]:
    """Sum of per-problem ranks; a player missing from a problem ranks last there."""
    columns = []
    for results in per_problem:
        seen = {r.player for r in results}
        columns.append(
            rank_problem([*results, *(Result(p, None) for p in players if p not in seen)])
        )
    standings = [
        Standing(p, sum(c[p] for c in columns), tuple(c[p] for c in columns)) for p in players
    ]
    return sorted(standings, key=lambda s: (s.total, s.player))


def precision(gap: float, floor: float = 1e-8) -> float:
    """log10 of a gap, floored: the reveal's 'digits found'."""
    return math.log10(max(gap, floor))
