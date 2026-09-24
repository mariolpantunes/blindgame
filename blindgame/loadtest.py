"""Load test: simulated students play a running blindgame server end to end.

    python -m blindgame.loadtest https://tunnel.example.org --students 30

Each student joins (the joins are spread over `--ramp` seconds), plays every
problem with a random pause between evaluations, sometimes stops a problem
early, opens every reveal and, like the final screen, the live board socket.
The report gives errors, latency percentiles per request type and the bytes
received. The students join the running game: restart the server afterwards
(a new game) unless the contest file pins a seed.
"""

import argparse
import json
import random
import statistics
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx2
from websockets.sync.client import connect


@dataclass
class Report:
    """Measurements shared by every student thread."""

    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: list[str] = field(default_factory=list)
    received: int = 0
    board_messages: int = 0
    finished: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, kind: str, seconds: float, size: int) -> None:
        """Record one successful request."""
        with self.lock:
            self.latencies[kind].append(seconds)
            self.received += size

    def fail(self, message: str) -> None:
        """Record one failure."""
        with self.lock:
            self.errors.append(message)

    def summary(self) -> str:
        """The report as text: one line per request type, then the totals."""
        lines = [f"{'request':<8} {'n':>5} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8}"]
        for kind, values in sorted(self.latencies.items()):
            ordered = sorted(values)
            p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
            lines.append(
                f"{kind:<8} {len(values):>5} {1000 * statistics.median(values):>8.0f}"
                f" {1000 * p95:>8.0f} {1000 * max(values):>8.0f}"
            )
        lines.append(
            f"students finished: {self.finished}, errors: {len(self.errors)}, "
            f"received: {self.received / 1e6:.1f} MB, board updates: {self.board_messages}"
        )
        lines.extend(f"  error: {e}" for e in self.errors[:10])
        return "\n".join(lines)


def _request(client: httpx2.Client, report: Report, kind: str, method: str, path: str, **kw):
    started = time.perf_counter()
    r = client.request(method, path, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"{kind} {path}: HTTP {r.status_code} {r.text[:120]}")
    report.add(kind, time.perf_counter() - started, r.num_bytes_downloaded)
    return r.json()


def _read_board(url: str, report: Report) -> None:
    """The final screen: open the board socket, read the standings, leave."""
    ws_url = url.replace("https://", "wss://").replace("http://", "ws://") + "/ws/board"
    with connect(ws_url) as ws:
        json.loads(ws.recv(timeout=30))
    with report.lock:
        report.board_messages += 1


def play(url: str, name: str, report: Report, think: float, rng: random.Random) -> None:
    """One student: join, play every problem, read every reveal, then the live board."""
    with httpx2.Client(base_url=url, timeout=60) as client:
        try:
            contest = _request(client, report, "contest", "GET", "/api/contest")
            _request(client, report, "join", "POST", "/api/join", json={"nickname": name})
            for k in range(contest["problems"]):
                # Some students stop early, the others spend the whole budget.
                n = contest["budget"] if rng.random() < 0.7 else rng.randint(1, contest["budget"])
                for _ in range(n):
                    time.sleep(rng.uniform(0, think))
                    x = [rng.random(), rng.random()]
                    _request(
                        client, report, "eval", "POST", f"/api/me/problems/{k}/eval", json={"x": x}
                    )
                if n < contest["budget"]:
                    _request(client, report, "stop", "POST", f"/api/me/problems/{k}/stop")
                _request(client, report, "reveal", "GET", f"/api/me/problems/{k}/reveal")
            _read_board(url, report)
            with report.lock:
                report.finished += 1
        except Exception as e:
            report.fail(f"{name}: {e}")


def run(url: str, students: int, ramp: float, think: float, seed: int) -> Report:
    """Play `students` students against `url` and return the measurements."""
    report = Report()
    tag = f"{seed:x}"[-4:]
    with ThreadPoolExecutor(max_workers=students) as pool:
        for k in range(students):
            rng = random.Random(seed + k)
            pool.submit(play, url.rstrip("/"), f"load-{tag}-{k:02d}", report, think, rng)
            time.sleep(ramp / max(students, 1))
    return report


def main(argv: list[str] | None = None) -> int:
    """Command line entry point; the exit code is 1 when any request failed."""
    parser = argparse.ArgumentParser(prog="python -m blindgame.loadtest", description=__doc__)
    parser.add_argument("url", help="the server, e.g. http://127.0.0.1:8000")
    parser.add_argument("--students", type=int, default=30)
    parser.add_argument("--ramp", type=float, default=10.0, help="seconds over which they join")
    parser.add_argument("--think", type=float, default=0.5, help="max pause between evaluations")
    parser.add_argument("--seed", type=int, default=int(time.time()))
    args = parser.parse_args(argv)
    started = time.perf_counter()
    report = run(args.url, args.students, args.ramp, args.think, args.seed)
    print(report.summary())
    print(f"wall time: {time.perf_counter() - started:.1f} s")
    print(json.dumps({"errors": len(report.errors), "finished": report.finished}))
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
