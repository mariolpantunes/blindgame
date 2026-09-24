import unittest
from dataclasses import replace

from fastapi.testclient import TestClient

from blindgame import server
from blindgame.config import parse
from blindgame.game import Game
from blindgame.server import COOKIE, create_app
from blindgame.store import Store

CFG = parse(
    {
        "id": "api",
        "problems": ["Sphere", "Levy", "Ackley"],
        "budget": 5,
        "reveal": {"algorithms": ["Random Search"], "runs": 2, "epochs": 2},
    }
)


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.game = Game(self.store, CFG)
        self.client = TestClient(create_app(self.game))

    def tearDown(self):
        self.store.close()

    def join(self, nickname: str, code: str = "") -> TestClient:
        client = TestClient(self.client.app)
        r = client.post("/api/join", json={"nickname": nickname, "code": code})
        self.assertEqual(r.status_code, 200, r.text)
        return client

    def spend(self, client: TestClient, problem: int, n: int = 5) -> None:
        for k in range(n):
            r = client.post(f"/api/me/problems/{problem}/eval", json={"x": [0.1 + 0.2 * k, 0.5]})
            self.assertEqual(r.status_code, 200, r.text)

    def test_public_contest_hides_landscapes(self):
        c = self.client.get("/api/contest").json()
        self.assertEqual((c["budget"], c["problems"]), (5, 3))
        self.assertNotIn("Sphere", str(c))

    def test_full_game(self):
        ana = self.join("ana")
        self.assertIn(COOKIE, ana.cookies)
        me = ana.get("/api/me").json()
        self.assertEqual((me["player"], me["current"], me["finished"]), ("ana", 0, False))

        self.assertEqual(ana.get("/api/me/problems/0/reveal").status_code, 409)
        self.assertEqual(
            ana.post("/api/me/problems/1/eval", json={"x": [0.5, 0.5]}).status_code, 409
        )
        for k in range(5):
            r = ana.post("/api/me/problems/0/eval", json={"x": [0.1 + 0.2 * k, 0.5]})
            self.assertEqual(r.json()["remaining"], 4 - k)
        self.assertEqual(
            ana.post("/api/me/problems/0/eval", json={"x": [0.5, 0.5]}).status_code, 409
        )
        reveal = ana.get("/api/me/problems/0/reveal").json()
        self.assertEqual(reveal["landscape"], CFG.spec.landscapes[0])
        self.assertEqual(len(reveal["machines"]), 1)

        self.assertEqual(ana.post("/api/me/restart").status_code, 409)  # not finished
        self.spend(ana, 1)
        self.spend(ana, 2)
        self.assertTrue(ana.get("/api/me").json()["finished"])
        again = ana.post("/api/me/restart").json()
        self.assertEqual((again["attempt"], again["counts"], again["current"]), (2, False, 0))

    def test_stop_endpoint(self):
        ana = self.join("ana")
        self.assertEqual(ana.post("/api/me/problems/0/stop").status_code, 409)
        self.spend(ana, 0, n=1)
        r = ana.post("/api/me/problems/0/stop")
        self.assertEqual(r.json()["current"], 1)
        self.assertEqual(ana.get("/api/me/problems/0/reveal").status_code, 200)

    def test_bad_queries(self):
        ana = self.join("ana")
        for body, code in (
            ({"x": [1.5, 0.5]}, 422),
            ({"x": [0.5]}, 422),
            ({"x": "a"}, 422),
        ):
            self.assertEqual(ana.post("/api/me/problems/0/eval", json=body).status_code, code)
        self.assertEqual(
            ana.post("/api/me/problems/9/eval", json={"x": [0.5, 0.5]}).status_code, 404
        )

    def test_players_need_a_valid_cookie(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.client.cookies.set(COOKIE, "forged")
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_join_errors(self):
        self.join("ana")
        self.assertEqual(self.client.post("/api/join", json={"nickname": "ana"}).status_code, 409)
        self.assertEqual(self.client.post("/api/join", json={"nickname": "   "}).status_code, 422)

    def test_code_and_closed(self):
        game = Game(self.store, replace(CFG, id="api2", code="K9"))
        client = TestClient(create_app(game))
        self.assertEqual(
            client.post("/api/join", json={"nickname": "a", "code": "x"}).status_code, 403
        )
        self.assertEqual(
            client.post("/api/join", json={"nickname": "a", "code": "k9"}).status_code, 200
        )
        game.cfg = replace(game.cfg, status="closed")
        r = client.post("/api/me/problems/0/eval", json={"x": [0.5, 0.5]})
        self.assertEqual(r.status_code, 423)

    def test_leave_clears_cookie(self):
        ana = self.join("ana")
        ana.post("/api/leave")
        self.assertEqual(ana.get("/api/me").status_code, 401)

    def test_board_has_no_values(self):
        ana = self.join("ana")
        self.join("rui")
        self.spend(ana, 0)
        board = self.client.get("/api/board").json()
        self.assertEqual([s["player"] for s in board["standings"]], ["ana", "rui"])
        self.assertEqual(board["standings"][0]["done"], 1)
        self.assertNotIn("Sphere", str(board))

    def test_board_built_once_per_version(self):
        first = self.client.get("/api/board").json()
        self.assertEqual(first, self.client.get("/api/board").json())
        self.join("ana")  # bumps the version
        self.assertEqual(len(self.client.get("/api/board").json()["standings"]), 1)

    def test_point_size_is_bounded(self):
        ana = self.join("ana")
        r = ana.post("/api/me/problems/0/eval", json={"x": [0.5] * 65})
        self.assertEqual(r.status_code, 422)

    def test_board_socket(self):
        server.BOARD_POLL = 0.01
        with self.client.websocket_connect("/ws/board") as ws:
            self.assertEqual(ws.receive_json()["standings"], [])
            self.join("ana")
            self.assertEqual(ws.receive_json()["standings"][0]["player"], "ana")

    def test_pages_served(self):
        for path in ("/", "/board"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("blindgame", r.text)
        for path in ("/static/style.css", "/static/js/play.js", "/static/js/colormap.js"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertEqual(r.headers["cache-control"], "no-cache")


if __name__ == "__main__":
    unittest.main()
