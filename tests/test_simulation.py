"""End-to-end: three students on a real server, over HTTP and the board WebSocket.

They join at different times, one drops mid-problem and comes back with the same
cookie, one stops a problem early, one finishes and starts a practice attempt,
and a watcher's board socket drops and reconnects. Then the server restarts
with a new clock seed: a new game, and the old cookies no longer work.
"""

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock

import httpx2
import uvicorn
from websockets.sync.client import connect

from blindgame import server
from blindgame.config import parse
from blindgame.game import Game
from blindgame.server import COOKIE, create_app
from blindgame.store import Store

FILE = {
    "id": "sim",
    "problems": ["Sphere", "Rastrigin", "Ackley"],
    "reveal": {"algorithms": ["Random Search", "Grey Wolf"], "runs": 2, "epochs": 3},
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    """The game served by uvicorn in a thread, reveals computed before serving."""

    def __init__(self, store: Store, clock: float):
        with mock.patch("blindgame.config.time.time", return_value=clock):
            self.game = Game(store, parse(FILE))
        for future in self.game.precompute():
            future.result()
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(
            create_app(self.game), host="127.0.0.1", port=self.port, log_level="warning"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "LiveServer":
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.02)
        raise RuntimeError("server did not start")

    def __exit__(self, *_exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class Student:
    """A browser: an HTTP client with a cookie jar it can lose and get back."""

    def __init__(self, url: str, nickname: str):
        self.url = url
        self.nickname = nickname
        self.client = httpx2.Client(base_url=url, timeout=30)
        self.statuses: list[int] = []

    def call(self, method: str, path: str, **kw) -> httpx2.Response:
        r = self.client.request(method, path, **kw)
        self.statuses.append(r.status_code)
        return r

    def join(self) -> None:
        r = self.call("POST", "/api/join", json={"nickname": self.nickname})
        assert r.status_code == 200, r.text

    def drop_and_reconnect(self) -> None:
        """Close the browser and open it again with the same cookie."""
        cookie = self.client.cookies[COOKIE]
        self.client.close()
        self.client = httpx2.Client(base_url=self.url, timeout=30, cookies={COOKIE: cookie})

    def evaluate(self, problem: int, n: int) -> None:
        for k in range(n):
            x = [0.05 + 0.09 * k, 0.9 - 0.08 * k]
            r = self.call("POST", f"/api/me/problems/{problem}/eval", json={"x": x})
            assert r.status_code == 200, r.text

    def reveal(self, problem: int) -> dict:
        started = time.perf_counter()
        r = self.call("GET", f"/api/me/problems/{problem}/reveal")
        assert r.status_code == 200, r.text
        return {**r.json(), "seconds": time.perf_counter() - started}


class SimulationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "game.db"))
        server.BOARD_POLL = 0.02

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_three_students(self):
        with LiveServer(self.store, clock=1_000_000.0) as live:
            budget = live.game.spec.budget
            self.assertEqual(budget, 10)  # 4D+D in 2D
            ana, rui, ze = (Student(live.url, n) for n in ("ana", "rui", "zé"))
            reveals: dict[str, dict] = {}
            boards: list[dict] = []
            errors: list[BaseException] = []
            ana_started = threading.Event()

            def watcher():
                """The projector: its socket drops once and reconnects."""
                ws_url = live.url.replace("http", "ws") + "/ws/board"
                with connect(ws_url) as ws:
                    boards.append(json.loads(ws.recv(timeout=10)))
                with connect(ws_url) as ws:  # reconnected
                    deadline = time.time() + 30
                    while time.time() < deadline:
                        board = json.loads(ws.recv(timeout=30))
                        boards.append(board)
                        if sum(s["done"] for s in board["standings"]) == 9:
                            return

            def play_ana():
                ana.join()
                ana_started.set()
                ana.evaluate(0, budget)
                reveals["ana"] = ana.reveal(0)
                ana.evaluate(1, 4)
                ana.drop_and_reconnect()  # the laptop lid closes mid-problem
                me = ana.call("GET", "/api/me").json()
                assert (me["current"], len(me["problems"][1]["queries"])) == (1, 4), me
                ana.evaluate(1, budget - 4)
                ana.evaluate(2, budget)
                assert ana.call("GET", "/api/me").json()["finished"]
                again = ana.call("POST", "/api/me/restart").json()
                assert (again["attempt"], again["counts"]) == (2, False), again
                ana.evaluate(0, budget)  # practice, on fresh instances
                reveals["ana-practice"] = ana.reveal(0)

            def play_rui():
                ana_started.wait(10)
                time.sleep(0.2)  # arrives a little later
                rui.join()
                rui.evaluate(0, 3)
                self.assertEqual(rui.call("POST", "/api/me/problems/0/stop").status_code, 200)
                reveals["rui"] = rui.reveal(0)
                rui.evaluate(1, budget)
                rui.evaluate(2, 1)
                rui.call("POST", "/api/me/problems/2/stop")

            def play_ze():
                ana_started.wait(10)
                time.sleep(0.5)  # arrives last
                ze.join()
                ze.evaluate(0, budget)
                reveals["zé"] = ze.reveal(0)
                ze.drop_and_reconnect()
                ze.evaluate(1, 2)
                ze.call("POST", "/api/me/problems/1/stop")
                ze.evaluate(2, budget)

            def guarded(fn):
                def run():
                    try:
                        fn()
                    except BaseException as e:  # surfaced below, with the thread's error
                        errors.append(e)

                return threading.Thread(target=run)

            threads = [guarded(f) for f in (watcher, play_ana, play_rui, play_ze)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=120)
            self.assertEqual(errors, [])

            # Nobody ever saw a server error.
            for s in (ana, rui, ze):
                self.assertTrue(all(code < 500 for code in s.statuses), s.nickname)
            # First attempts share instances: the same optimum for everyone.
            optima = {tuple(reveals[n]["x_opt"]) for n in ("ana", "rui", "zé")}
            self.assertEqual(len(optima), 1)
            self.assertNotEqual(tuple(reveals["ana-practice"]["x_opt"]), optima.pop())
            # Shared reveals were computed before serving: answered without waiting.
            for n in ("ana", "rui", "zé"):
                self.assertLess(reveals[n]["seconds"], 1.0, n)
            self.assertEqual(len(reveals["rui"]["you"]["points"]), 3)  # stopped early
            # The board followed everyone live, with ranks and progress, never values.
            final = boards[-1]
            done = {s["player"]: s["done"] for s in final["standings"]}
            self.assertEqual(done, {"ana": 3, "rui": 3, "zé": 3})
            self.assertNotIn("x_opt", json.dumps(boards))
            self.assertNotIn('"best"', json.dumps(boards))
            old_cookie = ana.client.cookies[COOKIE]
            first_key = live.game.cfg.key

        # A restart is a new game: new seed, new contest, old cookies rejected.
        with LiveServer(self.store, clock=1_000_600.0) as live:
            self.assertNotEqual(live.game.cfg.key, first_key)
            back = httpx2.Client(base_url=live.url, cookies={COOKIE: old_cookie})
            self.assertEqual(back.get("/api/me").status_code, 401)
            self.assertEqual(live.game.board()["standings"], [])
            back.close()
        for s in (ana, rui, ze):
            s.client.close()


if __name__ == "__main__":
    unittest.main()
