"""CLI entry point: `python -m blindgame --config contest.yaml [--db FILE] [--reset]`.

The contest file is the teacher's only control: edit it and restart the server.
"""

import argparse
import sys

import uvicorn

from .config import load
from .game import Game
from .server import create_app
from .store import Conflict, Store


def main() -> None:
    """Parse the command line, load the contest file and serve the game."""
    parser = argparse.ArgumentParser(
        prog="blindgame", description="Feel like a black-box optimizer."
    )
    parser.add_argument("--config", default="contest.yaml", help="contest file (YAML)")
    parser.add_argument("--db", default="blindgame.db", help="SQLite file with players and queries")
    parser.add_argument(
        "--reset", action="store_true", help="wipe this contest's players and results first"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    try:
        cfg = load(args.config)
        game = Game(Store(args.db), cfg, reset=args.reset)
    except (OSError, ValueError, Conflict) as e:
        sys.exit(f"blindgame: {e}")
    print(
        f"blindgame: '{cfg.title}' ({cfg.id}), {cfg.spec.n_problems} problems, "
        f"budget {cfg.spec.budget}, {cfg.status}"
    )
    # The frp tunnel connects from localhost: trust its X-Forwarded-Proto (https).
    uvicorn.run(
        create_app(game),
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
