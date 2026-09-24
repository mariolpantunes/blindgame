# blindgame

Feel like a black-box optimizer. Students minimise hidden 2D functions by hand, with a
budget of 5 evaluations per problem, in the spirit of the GECCO 2025 Fun Competition.
Functions, samplers and reference optimizers come from
[pyBlindOpt](https://github.com/mariolpantunes/pyBlindOpt).

> Status: v0.1.0, playable. See `.agent/PLAN.md`.

## Playing

The game is self-paced and fully automatic. The teacher's only control is a contest file
(`contest.yaml`, copied from `contest.example.yaml`): title, seed, functions, budget rule,
optional join code, open/closed, and which pyBlindOpt optimizers appear in the reveal. Edit
it and restart the server.

| Who | Page | What |
| :-- | :-- | :-- |
| Students | `/` | Join with a nickname (and the code, if the file sets one). Play P1…Pn in order: click the dark box to aim (or type x₁, x₂), press **Evaluate**. The budget is D²+1 evaluations per problem (5 in 2D), no undo. Scroll to zoom, drag to pan, click a history row to re-aim. |
| | reveal | After each problem's budget: the true colour map, your points, one run of each optimizer with the same budget (click a row to hide its path), the optimum, and the share of each optimizer's runs you beat. |
| | final | Your summary per problem and the live leaderboard. Reloading after finishing starts a practice attempt on fresh instances; only the first attempt counts. |
| Projector | `/board` | Live standings: nicknames, sum of per-problem ranks, progress. No values. |

- **Private results:** each student sees only their own points and values.
- **Own instances:** every attempt gets its own shift, rotation and scale of the same function sequence, so a revealed answer is useless to a neighbour.
- **Scoring:** students are ranked per problem by the distance to the optimum in the function's own units, which compares fairly across instances. Ties go to whoever reached their best in fewer evaluations.
- **Probe colours:** while playing, probes are coloured by their rank among the player's own values (gold = best), never by f.

## Deployment in class (frp tunnel)

eduroam isolates clients, so students cannot reach the teacher laptop directly. The
server runs on the laptop, and a self-hosted [frp](https://github.com/fatedier/frp) tunnel
publishes it at **https://tunnel.hrun.mooo.com**. Both connections to hrun leave the
laptop over HTTPS (443), so they pass eduroam.

```text
student ──https──> nginx (hrun) ──> frps (hrun, docker) <══wss:443══ frpc (laptop) ──> blindgame :8000
```

The server and the tunnel are two separate processes. Start them in two terminals:

```bash
# 1. the game
venv/bin/python -m blindgame --config contest.yaml --port 8000
#    --db FILE (default ./blindgame.db), --reset wipes this contest id's results

# 2. the tunnel (reads FRP_AUTH_TOKEN from .env)
set -a; . ./.env; set +a
frpc -c deploy/frpc.toml
```

`frpc` logs `start proxy success` once the site is live. Stop it with `Ctrl+C`, and the
address returns 404 again.

### Requirements

- `frpc` 0.71.0 on the laptop (`~/.local/bin/frpc`), from the
  [frp releases](https://github.com/fatedier/frp/releases). frp guarantees that frpc and
  frps work together across 9 minor versions. To upgrade, bump the `frps` image tag on
  hrun first (GHCR has no `:latest`), then replace `frpc`.
- `.env` (git-ignored) with `FRP_AUTH_TOKEN` (same value as in `~/services/.env` on hrun).

### Server side (hrun, already set up)

| Piece | Where |
| :-- | :-- |
| `frps` service, `ghcr.io/fatedier/frps:v0.71.0`, ports 7000/7080 on loopback only | `~/services/compose.yml` |
| `frps.toml` (token, ports) | `$FRPS_CONFIG` on the ZFS pool, path set in `~/services/.env` |
| nginx site: `/~!frp` → frps control, `/` → frps vhost | `/etc/nginx/conf.d/tunnel.conf` (copy in `deploy/hrun/tunnel.conf`) |
| TLS certificate for `tunnel.hrun.mooo.com` | root `acme.sh` (`--nginx`), renewed by its cron job |

To publish another local port, change `localPort` in `deploy/frpc.toml`. Only one app
can be published at a time.

## Development

```bash
python3.12 -m venv venv
venv/bin/pip install -q --upgrade "pip>=25.1"
venv/bin/pip install -q --upgrade . --group test
pre-commit install          # run the CI gate on every commit
pre-commit run --all-files
```

The pre-commit hooks and `.github/workflows/ci.yml` run the same checks: ruff (lint,
docstrings and format), basedpyright, vulture, `node --check` on `blindgame/static/js`,
unittest, and coverage (at least 95%). Hooks use the tools installed on the machine
(`pipx install ruff basedpyright vulture pre-commit`); CI pins the same versions
(ruff 0.16.6, basedpyright 1.39.10, vulture 2.16, Python 3.12, Node 24), so a tool upgrade
changes the pin in `ci.yml` in the same commit. The venv holds only runtime and test
dependencies.

### Layout

```text
blindgame/
├── problems.py   # pyBlindOpt landscapes behind hidden, seeded transforms (unit box → native scale)
├── contest.py    # ContestSpec, budget rules (2D+1, D²+1, 2^D+1), BBComp-style ranking by gap
├── config.py     # contest.yaml → ContestConfig (strict: unknown keys are errors)
├── reveal.py     # colour map + pyBlindOpt optimizers capped at the player's budget
├── game.py       # service: attempts, play order, evaluation, reveal, board
├── store.py      # SQLite: players (hashed tokens), attempts, query log (budget + order atomic)
├── server.py     # FastAPI: player API (HttpOnly cookie), board REST + WebSocket, static UI
├── __main__.py   # CLI: --config, --db, --reset
└── static/       # play (index) and board pages; vanilla ES modules, Nord theme
contest.example.yaml  # the teacher's file, documented
.github/workflows/ci.yml + .pre-commit-config.yaml   # the same gate, remote and local
deploy/           # frp tunnel: nginx site for hrun, frpc config for the laptop
tests/
```
