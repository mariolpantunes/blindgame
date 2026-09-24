# blindgame

Feel like a black-box optimizer. Students play the role of the algorithm: they minimise
hidden functions by hand, one evaluation at a time, knowing only the box and the numbers
they paid for. Inspired by the GECCO 2025 Fun Competition (manual optimisation by humans);
functions and reference optimizers come from
[pyBlindOpt](https://github.com/mariolpantunes/pyBlindOpt).

## Objective

The game makes the black-box setting tangible before it is formalised:

- **Sparse information:** a handful of evaluations in a dark box, each answering with one
  number. Where do you look first, and when do you stop exploring?
- **Humans against machines:** after each problem, pyBlindOpt optimizers run with the
  student's exact budget on the same instance, so students see what random search, local
  search and population methods would have done in their place.
- **Landscapes:** the reveal shows the function they were blind to: funnels, valleys,
  deceptive basins, regular grids of local minima.

## Rules

- **The box:** each problem is a hidden function on [0, 1]²; the goal is the lowest value.
- **The budget:** D²+1 evaluations per problem (5 in 2D). Every query costs one, repeats
  included, and there is no undo.
- **What you see:** your own points and their values, nothing else: no function name, no
  landscape, no optimum. Probes are coloured by their rank among your own values (gold =
  best), never by the value itself.
- **Order:** problems are played P1…Pn. A problem ends when its budget is spent, and its
  reveal follows: the true colour map, your points, one run of each optimizer with the same
  budget, the optimum, and the share of each optimizer's runs you beat.
- **Scoring:** per problem, players are ranked by their distance to the optimum in the
  function's own units; ties go to whoever reached their best in fewer evaluations. The
  score is the sum of ranks (lower is better); unplayed problems rank last.
- **Attempts:** only the first attempt counts. Reloading after finishing starts a practice
  attempt on fresh instances.
- **Privacy:** players see only their own results; the leaderboard shows nicknames, ranks
  and progress, never values.

## Architecture

```text
 browser                              teacher's laptop
 ┌──────────────────────┐   REST     ┌───────────────────────────────────────────────────┐
 │ /       play.js      │ ─────────> │ server.py   FastAPI: player API, board, static UI  │
 │         space.js     │            │    │                                               │
 │ /board  board.js     │ <── WS ─── │ game.py     attempts, order, evaluation, reveal   │
 └──────────────────────┘            │    ├── problems.py  hidden instances (pyBlindOpt) │
                                     │    ├── reveal.py    colour map + capped runs      │
                                     │    ├── store.py     SQLite: players, attempts,    │
                                     │    │                query log                     │
                                     │    └── config.py    contest.yaml → ContestConfig  │
                                     └───────────────────────────────────────────────────┘
```

- **The server is authoritative.** Functions are evaluated only on the server; the browser
  receives f(x) for the player's own queries and nothing else until a problem's reveal.
- **Hidden instances.** A query x ∈ [0, 1]² is mapped to the landscape's native scale,
  u = 10x − 5, then to z = o + Q(u − p), where o is the landscape's optimum, p a hidden
  optimum location and Q a random orthogonal map (a signed permutation for Schwefel and
  Lunacek, whose boundary walls must stay axis-aligned). The reported value is
  a·(f(z) − f(o)) + b, with a hidden scale a and offset b, so f* is unknown to the player.
  Every attempt draws its own p, Q, a and b from its seed, so a revealed answer is useless
  to anyone else. Ranking undoes a and b: gap = (best − b) / a.
- **Budgets and order are atomic.** The store checks the budget, and that the previous
  problem is finished, inside one SQLite transaction, so concurrent requests cannot
  overspend or skip ahead.
- **Capped optimizers.** For the reveal, each pyBlindOpt optimizer runs on the player's own
  instance through a wrapper that records the first B evaluations and answers the rest
  with a huge value: exactly what the optimizer would learn with the player's budget,
  whatever its population size. Results are cached per instance.
- **Live board.** A WebSocket pushes the standings after every evaluation; the board is
  built once per change, whatever the number of open screens.
- **Frontend.** Vanilla ES modules, no build step: a canvas view of the box (starfield,
  zoom and pan; the colour map, optimizer paths and optimum in the reveal). UI files are
  served with `Cache-Control: no-cache`, so an update reaches every browser.

| Module | Role |
| :-- | :-- |
| `problems.py` | the 11 pyBlindOpt landscapes, their optima, the seeded instance transform |
| `contest.py` | contest definition, budget rules (2D+1, D²+1, 2^D+1, or a number), ranking |
| `config.py` | the teacher's YAML file (strict: an unknown key is an error) |
| `reveal.py` | colour map and pyBlindOpt runs capped at the player's budget |
| `game.py` | the game as a service: joins, attempts, evaluation, reveal, board |
| `store.py` | SQLite persistence; player tokens stored as SHA-256 only |
| `server.py` | HTTP API (player identified by an HttpOnly cookie), WebSocket, static files |
| `__main__.py` | CLI: `--config`, `--db`, `--reset`, `--host`, `--port` |

| Method | Path | Purpose |
| :-- | :-- | :-- |
| `GET` | `/api/contest` | public facts: title, budget, number of problems, whether a code is needed |
| `POST` | `/api/join` | `{nickname, code}` → player cookie |
| `GET` | `/api/me` | the current attempt: progress and the player's own queries |
| `POST` | `/api/me/problems/{k}/eval` | `{x: [x1, x2]}` → f(x), remaining budget |
| `GET` | `/api/me/problems/{k}/reveal` | after problem k's budget: the landscape, optimum and optimizers |
| `POST` | `/api/me/restart` | a practice attempt, once the current one is finished |
| `GET` / `WS` | `/api/board`, `/ws/board` | the leaderboard (live over the WebSocket) |

## Installation

```bash
git clone https://github.com/mariolpantunes/blindgame
cd blindgame
python3 -m venv venv
venv/bin/pip install .
```

## Running a class

The teacher's only control is a contest file: copy `contest.example.yaml` to
`contest.yaml` and set the title, seed, functions (a count or a list), budget rule, an
optional join code, `status: open|closed`, and the optimizers shown in the reveal.

Serve it on the local network, so students on the same network can reach the laptop:

```bash
venv/bin/python -m blindgame --config contest.yaml --host 0.0.0.0 --port 8000
```

Students open `http://<laptop-ip>:8000`; the projector shows `http://<laptop-ip>:8000/board`.

Changing the game itself (seed, functions, dimension, budget) under the same `id` is
refused unless the server starts with `--reset`, which wipes that contest's results; title,
code, status and the reveal can change at any time (restart the server). Results live in
`blindgame.db` (`--db` to change).

### Behind a closed firewall

When the network isolates clients (e.g. eduroam), publish the laptop through the frp tunnel
at `https://tunnel.hrun.mooo.com` with the [frp](https://github.com/fatedier/frp) client:

```toml
# frpc.toml
serverAddr = "tunnel.hrun.mooo.com"
serverPort = 443
auth.method = "token"
auth.token = "{{ .Envs.FRP_AUTH_TOKEN }}"
transport.protocol = "wss"
transport.tls.enable = false

[[proxies]]
name = "blindgame"
type = "http"
localIP = "127.0.0.1"
localPort = 8000
customDomains = ["tunnel.hrun.mooo.com"]
requestHeaders.set.x-forwarded-proto = "https"
```

The token stays out of `frpc.toml`: put `FRP_AUTH_TOKEN=...` in a `.env` file (git-ignored)
and load it into a subshell that runs the client, so it never reaches your shell history:

```bash
venv/bin/python -m blindgame --config contest.yaml          # terminal 1
(set -a; . ./.env; frpc -c frpc.toml)                       # terminal 2
```

Students open `https://tunnel.hrun.mooo.com` once `frpc` logs `start proxy success`.

## Development

```bash
venv/bin/pip install --upgrade . --group test
PYTHONPATH=. venv/bin/python -m unittest discover -s tests
```

## License

MIT, see [LICENSE](LICENSE).
