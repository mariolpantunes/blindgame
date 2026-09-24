"""SQLite persistence: contests, players, attempts and the append-only query log.

The store is the single source of truth for budgets and play order: a query is
checked (budget left, previous problem finished) and recorded in one IMMEDIATE
transaction, so concurrent requests cannot overspend or skip ahead. Player
tokens are stored as SHA-256 digests only.
"""

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

from .contest import ContestSpec

SCHEMA = """
CREATE TABLE IF NOT EXISTS contests (
    id       TEXT PRIMARY KEY,
    spec     TEXT NOT NULL,
    created  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY,
    contest_id TEXT NOT NULL REFERENCES contests(id),
    nickname   TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created    REAL NOT NULL,
    UNIQUE (contest_id, nickname)
);
CREATE TABLE IF NOT EXISTS attempts (
    id        INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(id),
    number    INTEGER NOT NULL,
    seed      INTEGER NOT NULL,
    created   REAL NOT NULL,
    UNIQUE (player_id, number)
);
CREATE TABLE IF NOT EXISTS stops (
    attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    problem    INTEGER NOT NULL,
    created    REAL NOT NULL,
    PRIMARY KEY (attempt_id, problem)
);
CREATE TABLE IF NOT EXISTS reveals (
    key        TEXT PRIMARY KEY,
    contest_id TEXT NOT NULL,
    data       TEXT NOT NULL,
    created    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS queries (
    id         INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    problem    INTEGER NOT NULL,
    seq        INTEGER NOT NULL,
    x          TEXT NOT NULL,
    f          REAL NOT NULL,
    created    REAL NOT NULL,
    UNIQUE (attempt_id, problem, seq)
);
"""

NICKNAME_MAX = 24
# Attempt seeds stay below 2**31 so they are valid numpy seeds everywhere.
SEED_LIMIT = 2**31


class StoreError(Exception):
    """Base class; the API maps subclasses to HTTP status codes."""


class NotFound(StoreError):
    """Unknown player, contest or problem."""


class Conflict(StoreError):
    """Nickname taken, or a contest id reused with another setup."""


class ContestClosed(StoreError):
    """The contest file says `status: closed`."""


class OutOfOrder(StoreError):
    """A query for a problem before the previous one is finished."""


class BudgetExhausted(StoreError):
    """No evaluations left on this problem."""


@dataclass(frozen=True)
class Player:
    """A registered nickname in one contest."""

    id: int
    contest_id: str
    nickname: str


@dataclass(frozen=True)
class Attempt:
    """One pass through the problem sequence, with its own instances."""

    id: int
    player_id: int
    number: int  # 1 = the attempt that counts; later ones are practice
    seed: int  # the instances of this attempt


@dataclass(frozen=True)
class Query:
    """One recorded evaluation."""

    problem: int
    seq: int  # 1-based position within the budget for this problem
    x: tuple[float, ...]
    f: float


@dataclass(frozen=True)
class Best:
    """One attempt's outcome on one problem."""

    attempt_id: int
    problem: int
    best: float
    used: int  # evaluations it took to reach `best`
    spent: int  # evaluations on this problem so far


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    """Thread-safe access to the SQLite file (one connection, one re-entrant lock)."""

    def __init__(self, path: str = ":memory:"):
        """Open (and create) the database at `path`; ':memory:' for tests."""
        # One connection shared by FastAPI's worker threads: every access holds the lock.
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        """Close the connection."""
        with self._lock:
            self._db.close()

    def _fetch(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # --- contests ---------------------------------------------------------------

    def ensure_contest(self, cid: str, spec: ContestSpec, reset: bool = False) -> None:
        """Registers the contest. A different spec under the same id needs `reset`,
        which also wipes the contest's players, attempts and queries."""
        encoded = json.dumps(spec.to_dict(), sort_keys=True)
        with self._lock:
            row = self._db.execute("SELECT spec FROM contests WHERE id = ?", (cid,)).fetchone()
            if row is not None and row[0] != encoded and not reset:
                raise Conflict(
                    f"contest '{cid}' exists with another setup: use a new id or --reset"
                )
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if reset:
                    players = "SELECT id FROM players WHERE contest_id = ?"
                    attempts = f"SELECT id FROM attempts WHERE player_id IN ({players})"
                    self._db.execute(
                        f"DELETE FROM queries WHERE attempt_id IN ({attempts})", (cid,)
                    )
                    self._db.execute(f"DELETE FROM stops WHERE attempt_id IN ({attempts})", (cid,))
                    self._db.execute(f"DELETE FROM attempts WHERE player_id IN ({players})", (cid,))
                    self._db.execute("DELETE FROM players WHERE contest_id = ?", (cid,))
                    self._db.execute("DELETE FROM reveals WHERE contest_id = ?", (cid,))
                self._db.execute(
                    "INSERT INTO contests VALUES (?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET spec = excluded.spec",
                    (cid, encoded, time.time()),
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    # --- players ----------------------------------------------------------------

    def join(self, cid: str, nickname: str) -> tuple[Player, str]:
        """Registers a nickname; returns the player and their secret token."""
        nickname = " ".join(nickname.split())
        if not 1 <= len(nickname) <= NICKNAME_MAX:
            raise ValueError(f"nickname must have 1 to {NICKNAME_MAX} characters")
        token = secrets.token_urlsafe(24)
        with self._lock:
            try:
                cur = self._db.execute(
                    "INSERT INTO players (contest_id, nickname, token_hash, created) "
                    "VALUES (?, ?, ?, ?)",
                    (cid, nickname, _hash(token), time.time()),
                )
            except sqlite3.IntegrityError as e:
                raise Conflict(f"nickname '{nickname}' is taken") from e
        assert cur.lastrowid is not None
        return Player(cur.lastrowid, cid, nickname), token

    def player(self, token: str) -> Player:
        """The player owning `token`; NotFound otherwise."""
        rows = self._fetch(
            "SELECT id, contest_id, nickname FROM players WHERE token_hash = ?", (_hash(token),)
        )
        if not rows:
            raise NotFound("unknown player")
        return Player(*rows[0])

    def players(self, cid: str) -> list[Player]:
        """Every player of contest `cid`, in join order."""
        rows = self._fetch(
            "SELECT id, contest_id, nickname FROM players WHERE contest_id = ? ORDER BY id",
            (cid,),
        )
        return [Player(*r) for r in rows]

    # --- attempts ---------------------------------------------------------------

    def new_attempt(self, player: Player) -> Attempt:
        """Start the player's next attempt with a fresh random seed."""
        seed = secrets.randbelow(SEED_LIMIT)
        with self._lock:
            number = self._db.execute(
                "SELECT COALESCE(MAX(number), 0) + 1 FROM attempts WHERE player_id = ?",
                (player.id,),
            ).fetchone()[0]
            cur = self._db.execute(
                "INSERT INTO attempts (player_id, number, seed, created) VALUES (?, ?, ?, ?)",
                (player.id, number, seed, time.time()),
            )
        assert cur.lastrowid is not None
        return Attempt(cur.lastrowid, player.id, number, seed)

    def attempt(self, player: Player) -> Attempt:
        """The player's latest attempt, created on first use."""
        rows = self._fetch(
            "SELECT id, player_id, number, seed FROM attempts WHERE player_id = ? "
            "ORDER BY number DESC LIMIT 1",
            (player.id,),
        )
        return Attempt(*rows[0]) if rows else self.new_attempt(player)

    def first_attempts(self, cid: str) -> list[tuple[Player, Attempt]]:
        """Every player with the attempt that counts (players who never started: none)."""
        rows = self._fetch(
            "SELECT p.id, p.contest_id, p.nickname, a.id, a.player_id, a.number, a.seed "
            "FROM players p LEFT JOIN attempts a ON a.player_id = p.id AND a.number = 1 "
            "WHERE p.contest_id = ? ORDER BY p.id",
            (cid,),
        )
        return [(Player(*r[:3]), Attempt(*r[3:])) for r in rows if r[3] is not None]

    # --- queries ----------------------------------------------------------------

    def _done(self, attempt_id: int, problem: int, budget: int) -> bool:
        """Budget spent or stopped early (call inside a transaction)."""
        used = self._db.execute(
            "SELECT COUNT(*) FROM queries WHERE attempt_id = ? AND problem = ?",
            (attempt_id, problem),
        ).fetchone()[0]
        stopped = self._db.execute(
            "SELECT 1 FROM stops WHERE attempt_id = ? AND problem = ?", (attempt_id, problem)
        ).fetchone()
        return used >= budget or stopped is not None

    def _open(self, attempt: Attempt, problem: int, budget: int) -> int:
        """Checks the problem can be played now; returns evaluations spent on it."""
        if problem > 0 and not self._done(attempt.id, problem - 1, budget):
            raise OutOfOrder(f"finish problem {problem} first")
        if self._done(attempt.id, problem, budget):
            raise BudgetExhausted("this problem is finished")
        return self._db.execute(
            "SELECT COUNT(*) FROM queries WHERE attempt_id = ? AND problem = ?",
            (attempt.id, problem),
        ).fetchone()[0]

    def record(self, attempt: Attempt, problem: int, x, f: float, budget: int) -> Query:
        """Appends one evaluation if the problem is open and the previous one is done."""
        x = tuple(float(v) for v in x)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                used = self._open(attempt, problem, budget)
                self._db.execute(
                    "INSERT INTO queries (attempt_id, problem, seq, x, f, created) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (attempt.id, problem, used + 1, json.dumps(x), float(f), time.time()),
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return Query(problem, used + 1, x, float(f))

    def stop(self, attempt: Attempt, problem: int, budget: int) -> None:
        """Ends a problem before its budget is spent (at least one evaluation needed)."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if self._open(attempt, problem, budget) == 0:
                    raise OutOfOrder("evaluate at least one point before stopping")
                self._db.execute(
                    "INSERT INTO stops VALUES (?, ?, ?)", (attempt.id, problem, time.time())
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def stopped(self, attempt_ids: list[int]) -> set[tuple[int, int]]:
        """(attempt id, problem) pairs ended early."""
        if not attempt_ids:
            return set()
        marks = ",".join("?" * len(attempt_ids))
        rows = self._fetch(
            f"SELECT attempt_id, problem FROM stops WHERE attempt_id IN ({marks})",
            tuple(attempt_ids),
        )
        return {(a, p) for a, p in rows}

    def history(self, attempt: Attempt, problem: int | None = None) -> list[Query]:
        """The attempt's queries (optionally one problem), in order."""
        sql = "SELECT problem, seq, x, f FROM queries WHERE attempt_id = ?"
        args: tuple = (attempt.id,)
        if problem is not None:
            sql += " AND problem = ?"
            args += (problem,)
        rows = self._fetch(sql + " ORDER BY problem, seq", args)
        return [Query(p, s, tuple(json.loads(x)), f) for p, s, x, f in rows]

    def bests(self, attempt_ids: list[int]) -> list[Best]:
        """Per attempt and problem: best value and the query that first reached it."""
        if not attempt_ids:
            return []
        marks = ",".join("?" * len(attempt_ids))
        rows = self._fetch(
            "SELECT q.attempt_id, q.problem, q.f, MIN(q.seq), b.n FROM queries q "
            "JOIN (SELECT attempt_id, problem, MIN(f) AS best, COUNT(*) AS n FROM queries "
            f"      WHERE attempt_id IN ({marks}) GROUP BY attempt_id, problem) b "
            "  ON b.attempt_id = q.attempt_id AND b.problem = q.problem AND q.f = b.best "
            "GROUP BY q.attempt_id, q.problem",
            tuple(attempt_ids),
        )
        return [Best(*r) for r in rows]

    # --- reveals ----------------------------------------------------------------

    def reveal(self, key: str) -> dict | None:
        """A stored reveal (colour map and optimizer runs), or None."""
        rows = self._fetch("SELECT data FROM reveals WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else None

    def save_reveal(self, key: str, cid: str, data: dict) -> None:
        """Store a computed reveal; the same key always holds the same data."""
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO reveals VALUES (?, ?, ?, ?)",
                (key, cid, json.dumps(data), time.time()),
            )
