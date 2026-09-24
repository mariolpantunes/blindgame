"""The teacher's contest file (YAML): the whole setup of a game, no admin page.

Unknown keys are errors, so a typo cannot silently fall back to a default.
See contest.example.yaml.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import contest, problems, reveal

KEYS = {"id", "title", "seed", "dim", "problems", "budget", "code", "status", "reveal"}
REVEAL_KEYS = {"algorithms", "runs"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class ContestConfig:
    """A parsed contest file: the game (spec) plus runtime settings."""

    id: str
    title: str
    spec: contest.ContestSpec
    code: str = ""
    status: str = "open"
    algorithms: tuple[str, ...] = reveal.DEFAULT_ALGORITHMS
    runs: int = reveal.DEFAULT_RUNS

    @property
    def is_open(self) -> bool:
        """Whether players may join and evaluate."""
        return self.status == "open"

    def public(self) -> dict:
        """What players may know: the size of the box, never the landscapes."""
        s = self.spec
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "needs_code": bool(self.code),
            "dim": s.dim,
            "budget": s.budget,
            "bounds": [[0.0, 1.0]] * s.dim,
            "problems": s.n_problems,
            "runs": self.runs,
        }


def parse(data: object) -> ContestConfig:
    """Validate a loaded YAML mapping and build the config; ValueError on any mistake."""
    if not isinstance(data, dict):
        raise ValueError("the contest file must be a mapping")
    unknown = set(data) - KEYS
    if unknown:
        raise ValueError(f"unknown keys {sorted(unknown)}; allowed: {sorted(KEYS)}")
    cid = str(data.get("id", ""))
    if not ID_PATTERN.match(cid):
        raise ValueError("id is required: letters, digits, '.', '_' or '-', up to 64 characters")
    seed = int(data.get("seed", 0))
    dim = int(data.get("dim", contest.DEFAULT_DIM))
    budget = str(data.get("budget", contest.DEFAULT_BUDGET_RULE)).replace(" ", "")
    chosen = data.get("problems", contest.DEFAULT_PROBLEMS)
    if isinstance(chosen, int):
        if chosen < 1:
            raise ValueError("problems must be >= 1")
        spec = contest.ContestSpec.random(seed, chosen, dim, budget)
    elif isinstance(chosen, list):
        spec = contest.ContestSpec(seed, tuple(map(str, chosen)), dim, budget)
    else:
        raise ValueError(f"problems: a count or a list of {sorted(problems.LANDSCAPES)}")

    status = str(data.get("status", "open"))
    if status not in ("open", "closed"):
        raise ValueError("status must be 'open' or 'closed'")

    shown = data.get("reveal") or {}
    if not isinstance(shown, dict) or set(shown) - REVEAL_KEYS:
        raise ValueError(f"reveal: a mapping with {sorted(REVEAL_KEYS)}")
    algorithms = tuple(map(str, shown.get("algorithms", reveal.DEFAULT_ALGORITHMS)))
    unknown = [a for a in algorithms if a not in reveal.ALGORITHMS]
    if unknown:
        raise ValueError(f"unknown algorithms {unknown}; allowed: {list(reveal.ALGORITHMS)}")
    runs = int(shown.get("runs", reveal.DEFAULT_RUNS))
    if not 1 <= runs <= 200:
        raise ValueError("reveal.runs must be in [1, 200]")

    return ContestConfig(
        id=cid,
        title=str(data.get("title", cid)),
        spec=spec,
        code=str(data.get("code", "") or "").strip().upper(),
        status=status,
        algorithms=algorithms,
        runs=runs,
    )


def load(path: str | Path) -> ContestConfig:
    """Read and parse a contest file."""
    with open(path, encoding="utf-8") as f:
        return parse(yaml.safe_load(f))
