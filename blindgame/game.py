"""The game as a service: one contest from the teacher's file, self-paced players.

Each player plays P1..Pn in order, within an attempt. A problem's reveal unlocks
once its budget is spent; the attempt ends after the last problem. Everyone's
first attempt plays the same instances (derived from the contest seed), so their
reveals are computed once, at start-up, and stored in SQLite; the first attempt
is the one on the board. Reloading after finishing starts a practice attempt on
fresh instances of its own. The board shows nicknames, ranks and progress only.
"""

import hashlib
import hmac
import json
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache

from . import contest, reveal
from .config import ContestConfig
from .problems import Instance, make_instance
from .store import Attempt, ContestClosed, NotFound, OutOfOrder, Player, Store, StoreError

# Reveals kept in memory on top of SQLite; each holds a 128x128 grid (~0.5 MB).
MEMORY_REVEALS = 64


class WrongCode(StoreError):
    """The contest file sets a join code and the player gave another."""


@lru_cache(maxsize=256)
def _instance(name: str, seed: int, index: int, dim: int) -> Instance:
    return make_instance(name, seed, index, dim)


class Game:
    """The contest in play: joins, the attempt state, evaluations, reveals and the board."""

    def __init__(self, store: Store, cfg: ContestConfig, reset: bool = False):
        """Register the contest in the store (`reset` wipes its results first)."""
        self.store = store
        self.cfg = cfg
        store.ensure_contest(cfg.key, cfg.spec, reset)
        # Reveals are computed off the request path: at start-up for the shared
        # instances, during play for practice attempts.
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reveal")
        self._pending: dict[str, Future] = {}
        self._memory: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def spec(self) -> contest.ContestSpec:
        """The game definition from the contest file."""
        return self.cfg.spec

    def seed_of(self, attempt: Attempt) -> int:
        """Instance seed: the contest's for first attempts (shared), the attempt's otherwise."""
        return self.spec.seed if attempt.number == 1 else attempt.seed

    def instance(self, attempt: Attempt, problem: int) -> Instance:
        """The hidden instance of `problem` for this attempt (cached)."""
        s = self.spec
        return _instance(s.landscapes[problem], self.seed_of(attempt), problem, s.dim)

    # --- reveals: memory, then SQLite, then computed once ----------------------------

    def _key(self, seed: int, problem: int) -> str:
        """Everything a reveal depends on, hashed."""
        s, c = self.spec, self.cfg
        parts = [s.landscapes[problem], seed, problem, s.dim, s.budget, c.algorithms, c.runs]
        return hashlib.sha256(json.dumps([*parts, c.epochs]).encode()).hexdigest()

    def _compute(self, key: str, seed: int, problem: int) -> dict:
        s, c = self.spec, self.cfg
        ins = _instance(s.landscapes[problem], seed, problem, s.dim)
        data = {
            "field": reveal.landscape(ins) if s.dim == 2 else {},
            "machines": reveal.compare(ins, s.budget, c.algorithms, c.runs, c.epochs, seed),
        }
        self.store.save_reveal(key, self.cfg.key, data)
        return data

    def _remember(self, key: str, data: dict) -> dict:
        with self._lock:
            self._memory[key] = data
            self._memory.move_to_end(key)
            while len(self._memory) > MEMORY_REVEALS:
                self._memory.popitem(last=False)
            self._pending.pop(key, None)
        return data

    def _settle(self, key: str, future: Future) -> None:
        """Keep a finished reveal; forget a failed one, so the next request retries."""
        if future.exception() is None:
            self._remember(key, future.result())
        else:
            with self._lock:
                self._pending.pop(key, None)

    def _request(self, seed: int, problem: int) -> Future | dict:
        """The reveal if it is ready, else the computation producing it (started once)."""
        key = self._key(seed, problem)
        with self._lock:
            if key in self._memory:
                return self._memory[key]
            if key in self._pending:
                return self._pending[key]
        stored = self.store.reveal(key)
        if stored is not None:
            return self._remember(key, stored)
        with self._lock:
            if key not in self._pending:
                future = self._workers.submit(self._compute, key, seed, problem)
                future.add_done_callback(lambda f: self._settle(key, f))
                self._pending[key] = future
            return self._pending[key]

    def reveal_data(self, attempt: Attempt, problem: int) -> dict:
        """Colour map and optimizer runs for one instance, waiting if still computing."""
        got = self._request(self.seed_of(attempt), problem)
        return got.result() if isinstance(got, Future) else got

    def prepare(self, attempt: Attempt, problem: int) -> None:
        """Start computing a problem's reveal in the background, unless already known."""
        if 0 <= problem < self.spec.n_problems:
            self._request(self.seed_of(attempt), problem)

    def precompute(self) -> list[Future]:
        """Queue the reveals of the shared instances (all problems); returns the pending ones."""
        requests = [self._request(self.spec.seed, k) for k in range(self.spec.n_problems)]
        return [r for r in requests if isinstance(r, Future)]

    # --- players ------------------------------------------------------------------

    def join(self, nickname: str, code: str = "") -> tuple[Player, str]:
        """Register a player and their first attempt; returns the player and the secret token."""
        if not self.cfg.is_open:
            raise ContestClosed("the contest is closed")
        if self.cfg.code and not hmac.compare_digest(
            code.strip().upper().encode(), self.cfg.code.encode()
        ):
            raise WrongCode("wrong contest code")
        player, token = self.store.join(self.cfg.key, nickname)
        self.store.new_attempt(player)
        return player, token

    def player(self, token: str) -> Player:
        """The player behind a cookie token, if they belong to this contest."""
        p = self.store.player(token)
        if p.contest_id != self.cfg.key:
            raise NotFound("unknown player")  # a cookie from another contest
        return p

    def finished(self, attempt: Attempt) -> list[bool]:
        """Per problem: budget spent or stopped early."""
        spent = [0] * self.spec.n_problems
        for q in self.store.history(attempt):
            spent[q.problem] += 1
        stopped = {p for _, p in self.store.stopped([attempt.id])}
        return [n >= self.spec.budget or i in stopped for i, n in enumerate(spent)]

    def current(self, attempt: Attempt) -> int:
        """Index of the problem being played; n_problems once the attempt is over."""
        done = self.finished(attempt)
        return next((i for i, d in enumerate(done) if not d), len(done))

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
        if q.seq == 1:
            self.prepare(attempt, problem)
        remaining = self.spec.budget - q.seq
        return {"seq": q.seq, "x": list(q.x), "f": q.f, "remaining": remaining}

    def stop(self, player: Player, problem: int) -> None:
        """End the current problem early; its reveal unlocks."""
        if not self.cfg.is_open:
            raise ContestClosed("the contest is closed")
        if not 0 <= problem < self.spec.n_problems:
            raise NotFound(f"problem {problem + 1} not found")
        self.store.stop(self.store.attempt(player), problem, self.spec.budget)

    def reveal(self, player: Player, problem: int) -> dict:
        """What problem `problem` really was, once its budget is spent."""
        if not 0 <= problem < self.spec.n_problems:
            raise NotFound(f"problem {problem + 1} not found")
        attempt = self.store.attempt(player)
        queries = self.store.history(attempt, problem)
        if not self.finished(attempt)[problem]:
            raise OutOfOrder("finish this problem first (spend the budget or stop)")
        ins = self.instance(attempt, problem)
        data = self.reveal_data(attempt, problem)
        field, machines = data["field"], data["machines"]
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
                    "start": m["start"],
                    "trail": m["trail"],
                    "best": m["best"],
                    "evaluations": m["evaluations"],
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
        entries = self.store.first_attempts(self.cfg.key)
        bests = self.store.bests([a.id for _, a in entries])
        by_attempt = {a.id: p.nickname for p, a in entries}
        seeds = {a.id: a.seed for _, a in entries}
        per_problem: list[list[contest.Result]] = [[] for _ in range(self.spec.n_problems)]
        done = dict.fromkeys(by_attempt.values(), 0)
        stopped = self.store.stopped(list(by_attempt))
        for b in bests:
            name = by_attempt[b.attempt_id]
            if b.spent >= self.spec.budget or (b.attempt_id, b.problem) in stopped:
                done[name] += 1
            ins = self.instance(
                Attempt(b.attempt_id, 0, 1, seeds[b.attempt_id]), b.problem
            )  # shared
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
