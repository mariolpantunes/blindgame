"""The game as a service: one contest from the teacher's file, self-paced players.

Each player plays P1..Pn in order, within an attempt. A problem's reveal unlocks
once its budget is spent; the attempt ends after the last problem. Only a
player's first attempt counts; reloading after finishing starts a practice
attempt on fresh instances. Players only ever see their own values: the board
shows nicknames, ranks and progress.
"""

import hmac
from functools import lru_cache

from . import contest, reveal
from .config import ContestConfig
from .problems import Instance, make_instance
from .store import Attempt, ContestClosed, NotFound, OutOfOrder, Player, Store, StoreError


class WrongCode(StoreError):
    """The contest file sets a join code and the player gave another."""


@lru_cache(maxsize=256)
def _instance(name: str, seed: int, index: int, dim: int) -> Instance:
    return make_instance(name, seed, index, dim)


# Recomputing one entry takes ~0.1 s; each holds a 128x128 grid as Python floats (~0.5 MB).
@lru_cache(maxsize=64)
def _machines(
    name: str, seed: int, index: int, dim: int, budget: int, algorithms: tuple[str, ...], runs: int
) -> tuple[dict, list[dict]]:
    """The reveal's fixed part for one instance: colour map and optimizer runs."""
    ins = _instance(name, seed, index, dim)
    field = reveal.landscape(ins) if dim == 2 else {}
    return field, reveal.compare(ins, budget, algorithms, runs, seed)


class Game:
    """The contest in play: joins, the attempt state, evaluations, reveals and the board."""

    def __init__(self, store: Store, cfg: ContestConfig, reset: bool = False):
        """Register the contest in the store (`reset` wipes its results first)."""
        self.store = store
        self.cfg = cfg
        store.ensure_contest(cfg.id, cfg.spec, reset)

    @property
    def spec(self) -> contest.ContestSpec:
        """The game definition from the contest file."""
        return self.cfg.spec

    def instance(self, attempt: Attempt, problem: int) -> Instance:
        """The hidden instance of `problem` for this attempt (cached)."""
        s = self.spec
        return _instance(s.landscapes[problem], attempt.seed, problem, s.dim)

    # --- players ------------------------------------------------------------------

    def join(self, nickname: str, code: str = "") -> tuple[Player, str]:
        """Register a player and their first attempt; returns the player and the secret token."""
        if not self.cfg.is_open:
            raise ContestClosed("the contest is closed")
        if self.cfg.code and not hmac.compare_digest(
            code.strip().upper().encode(), self.cfg.code.encode()
        ):
            raise WrongCode("wrong contest code")
        player, token = self.store.join(self.cfg.id, nickname)
        self.store.new_attempt(player)
        return player, token

    def player(self, token: str) -> Player:
        """The player behind a cookie token, if they belong to this contest."""
        p = self.store.player(token)
        if p.contest_id != self.cfg.id:
            raise NotFound("unknown player")  # a cookie from another contest
        return p

    def current(self, attempt: Attempt) -> int:
        """Index of the problem being played; n_problems once the attempt is over."""
        spent = [0] * self.spec.n_problems
        for q in self.store.history(attempt):
            spent[q.problem] += 1
        return next((i for i, n in enumerate(spent) if n < self.spec.budget), len(spent))

    def state(self, player: Player) -> dict:
        """The player's current attempt: progress and their own queries only."""
        attempt = self.store.attempt(player)
        history = self.store.history(attempt)
        current = self.current(attempt)
        return {
            "player": player.nickname,
            "contest": self.cfg.public(),
            "attempt": attempt.number,
            "counts": attempt.number == 1,
            "current": current,
            "finished": current >= self.spec.n_problems,
            "problems": [
                {
                    "index": i,
                    "queries": [
                        {"seq": q.seq, "x": list(q.x), "f": q.f} for q in history if q.problem == i
                    ],
                }
                for i in range(min(current + 1, self.spec.n_problems))
            ],
        }

    def restart(self, player: Player) -> Attempt:
        """A practice attempt; only once the current one is over."""
        attempt = self.store.attempt(player)
        if self.current(attempt) < self.spec.n_problems:
            raise OutOfOrder("finish the current attempt first")
        return self.store.new_attempt(player)

    # --- playing ------------------------------------------------------------------

    def evaluate(self, player: Player, problem: int, x) -> dict:
        """Evaluate `x` on the current problem and record it.

        Raises ContestClosed, NotFound, OutOfOrder, BudgetExhausted, or
        ValueError for a point outside the box.
        """
        if not self.cfg.is_open:
            raise ContestClosed("the contest is closed")
        if not 0 <= problem < self.spec.n_problems:
            raise NotFound(f"problem {problem + 1} not found")
        attempt = self.store.attempt(player)
        f = float(self.instance(attempt, problem)(x))  # ValueError: bad point
        q = self.store.record(attempt, problem, x, f, self.spec.budget)
        remaining = self.spec.budget - q.seq
        return {"seq": q.seq, "x": list(q.x), "f": q.f, "remaining": remaining}

    def reveal(self, player: Player, problem: int) -> dict:
        """What problem `problem` really was, once its budget is spent."""
        if not 0 <= problem < self.spec.n_problems:
            raise NotFound(f"problem {problem + 1} not found")
        attempt = self.store.attempt(player)
        queries = self.store.history(attempt, problem)
        if len(queries) < self.spec.budget:
            raise OutOfOrder("spend the whole budget on this problem first")
        s = self.spec
        ins = self.instance(attempt, problem)
        field, machines = _machines(
            s.landscapes[problem],
            attempt.seed,
            problem,
            s.dim,
            s.budget,
            self.cfg.algorithms,
            self.cfg.runs,
        )
        best = min(q.f for q in queries)
        gap = ins.gap(best)
        return {
            "problem": problem,
            "landscape": ins.name,
            "description": ins.landscape.description,
            "x_opt": ins.x_opt.tolist(),
            "f_opt": ins.f_opt,
            "field": field,
            "you": {
                "points": [{"seq": q.seq, "x": list(q.x), "f": q.f} for q in queries],
                "best": best,
                "gap": gap,
                "precision": contest.precision(gap),
            },
            "machines": [
                {
                    "name": m["name"],
                    "path": m["path"],
                    "median_gap": m["median_gap"],
                    "precision": contest.precision(m["median_gap"]),
                    "you_beat": reveal.percentile(gap, m["gaps"]),
                }
                for m in machines
            ],
        }

    # --- board --------------------------------------------------------------------

    def board(self) -> dict:
        """Standings over first attempts: nicknames, ranks, progress. No values."""
        entries = self.store.first_attempts(self.cfg.id)
        bests = self.store.bests([a.id for _, a in entries])
        by_attempt = {a.id: p.nickname for p, a in entries}
        seeds = {a.id: a.seed for _, a in entries}
        per_problem: list[list[contest.Result]] = [[] for _ in range(self.spec.n_problems)]
        done = dict.fromkeys(by_attempt.values(), 0)
        for b in bests:
            name = by_attempt[b.attempt_id]
            if b.spent >= self.spec.budget:
                done[name] += 1
            ins = self.instance(Attempt(b.attempt_id, 0, 1, seeds[b.attempt_id]), b.problem)
            per_problem[b.problem].append(contest.Result(name, ins.gap(b.best), b.used))
        names = [p.nickname for p, _ in entries]
        standings = contest.leaderboard(per_problem, names)
        return {
            "contest": self.cfg.public(),
            "standings": [
                {
                    "player": s.player,
                    "total": s.total,
                    "ranks": list(s.ranks),
                    "done": done[s.player],
                }
                for s in standings
            ],
        }
