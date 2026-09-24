"""FastAPI application: player API, live board, static UI.

The server is authoritative. Hidden instances are rebuilt from the contest file
and each attempt's seed, and evaluated here only; players get f(x) for their
own queries and nothing else until a problem's reveal. Players are identified
by an HttpOnly cookie. There is no admin API: the teacher edits the contest file.
"""

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from . import __version__
from .game import Game, WrongCode
from .store import (
    BudgetExhausted,
    Conflict,
    ContestClosed,
    NotFound,
    OutOfOrder,
    Player,
    StoreError,
)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
COOKIE = "blindgame_player"
# How often a board socket checks for new evaluations.
BOARD_POLL = 0.5
ERRORS = {
    NotFound: 404,
    Conflict: 409,
    BudgetExhausted: 409,
    OutOfOrder: 409,
    WrongCode: 403,
    ContestClosed: 423,
}


class Versions:
    """A counter bumped on every change the board shows, and the board it last built.

    Every open board socket asks for the board after each change; building it
    once per version keeps a full class from recomputing it once per socket.
    """

    def __init__(self):
        """Start at version 0, with nothing built."""
        self.value = 0
        self._built: tuple[int, dict] | None = None

    def bump(self) -> None:
        """Mark the board as changed."""
        self.value += 1

    def board(self, game: Game) -> dict:
        """The board for the current version (built at most once per version)."""
        version = self.value
        if self._built is None or self._built[0] != version:
            self._built = (version, game.board())
        return self._built[1]


class Join(BaseModel):
    """Body of POST /api/join."""

    nickname: str = Field(min_length=1, max_length=64)
    code: str = Field("", max_length=32)


class Query(BaseModel):
    """Body of POST /api/me/problems/{k}/eval: one point of the unit box."""

    x: list[float] = Field(max_length=64)


def create_app(game: Game) -> FastAPI:
    """Build the FastAPI app around one game."""
    app = FastAPI(title="blindgame", version=__version__)
    versions = Versions()

    @app.middleware("http")
    async def revalidate(request: Request, call_next):
        """Browsers must revalidate the UI (ETag, cheap), so an update reaches every student."""
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(StoreError)
    def store_error(_: Request, e: StoreError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=ERRORS.get(type(e), 400))

    def player(request: Request) -> Player:
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "join the game first")
        try:
            return game.player(token)
        except NotFound as e:
            raise HTTPException(401, "unknown player, join again") from e

    @app.get("/api/contest")
    def get_contest() -> dict:
        return game.cfg.public()

    @app.post("/api/join")
    def join(req: Join, request: Request, response: Response) -> dict:
        try:
            p, token = game.join(req.nickname, req.code)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=7 * 24 * 3600,
        )
        versions.bump()
        return {"player": p.nickname}

    @app.post("/api/leave")
    def leave(response: Response) -> dict:
        response.delete_cookie(COOKIE)
        return {}

    @app.get("/api/me")
    def me(p: Annotated[Player, Depends(player)]) -> dict:
        return game.state(p)

    @app.post("/api/me/restart")
    def restart(p: Annotated[Player, Depends(player)]) -> dict:
        game.restart(p)
        return game.state(p)

    @app.post("/api/me/problems/{problem}/eval")
    def evaluate(problem: int, req: Query, p: Annotated[Player, Depends(player)]) -> dict:
        try:
            out = game.evaluate(p, problem, req.x)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        versions.bump()
        return out

    @app.post("/api/me/problems/{problem}/stop")
    def stop(problem: int, p: Annotated[Player, Depends(player)]) -> dict:
        game.stop(p, problem)
        versions.bump()
        return game.state(p)

    @app.get("/api/me/problems/{problem}/reveal")
    def get_reveal(problem: int, p: Annotated[Player, Depends(player)]) -> dict:
        return game.reveal(p, problem)

    @app.get("/api/board")
    def get_board() -> dict:
        return versions.board(game)

    @app.websocket("/ws/board")
    async def board_socket(ws: WebSocket) -> None:
        """Sends the board on connect and after every change (polled, see BOARD_POLL)."""
        await ws.accept()
        seen = -1
        try:
            while True:
                if versions.value != seen:
                    seen = versions.value
                    await ws.send_json(await asyncio.to_thread(versions.board, game))
                await asyncio.sleep(BOARD_POLL)
        except (WebSocketDisconnect, RuntimeError):
            pass  # client went away

    # --- static UI -------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/board", include_in_schema=False)
    def board_page() -> FileResponse:
        return FileResponse(STATIC / "board.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
