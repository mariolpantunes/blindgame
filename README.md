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
- **Humans against machines:** after each problem, pyBlindOpt optimizers solve the same
  instance, starting from an OBLESA population as large as the student's budget and running
  100 epochs, so students see where random search, local search and population methods get
  with a hundred times more evaluations.
- **Landscapes:** the reveal shows the function they were blind to: funnels, valleys,
  deceptive basins, regular grids of local minima.

## Rules

- **The box:** each problem is a hidden function on [0, 1]²; the goal is the lowest value.
- **The budget:** 5D evaluations per problem (the rule 4D+D: 10 in 2D). Every query costs
  one, repeats included, and there is no undo. You may stop a problem early (after at least
  one evaluation) with **Stop here**.
- **What you see:** your own points and their values, nothing else: no function name, no
  landscape, no optimum. Probes are coloured by their rank among your own values (gold =
  best), never by the value itself.
- **Order:** problems are played P1…Pn. A problem ends when its budget is spent or you stop,
  and its reveal follows: the true colour map, your points, each optimizer's initial
  population, best-so-far trail and final best, the optimum, the optimizer's median gap
  (lower is better) and the share of its runs you beat.
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
                                     │    ├── reveal.py    colour map + reference runs   │
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
  Everyone's first attempt plays the same p, Q, a and b, drawn from the run's seed; practice
  attempts draw their own. Ranking undoes a and b: gap = (best − b) / a.
- **A fresh game per start.** Unless the contest file pins a `seed`, the server seeds each
  start from the clock: the function order is reshuffled and every instance is new. Each
  start is its own contest in the database (`<id>-<seed>`).
- **Budgets, stops and order are atomic.** The store checks the budget, early stops and that
  the previous problem is finished inside one SQLite transaction, so concurrent requests
  cannot overspend or skip ahead.
- **Solutions computed up front.** Before serving, the server runs every optimizer on every
  shared instance (OBLESA start of B points, 100 epochs, several seeds) and stores the
  results in SQLite, so every reveal is instant. Practice attempts compute theirs in the
  background as soon as a problem starts.
- **Live board.** A WebSocket pushes the standings after every evaluation; the board is
  built once per change, whatever the number of open screens.
- **Frontend.** Vanilla ES modules, no build step: a canvas view of the box (starfield,
  zoom and pan; the colour map, optimizer paths and optimum in the reveal). UI files are
  served with `Cache-Control: no-cache`, so an update reaches every browser.

| Module | Role |
| :-- | :-- |
| `problems.py` | the 11 pyBlindOpt landscapes, their optima, the seeded instance transform |
| `contest.py` | contest definition, budget formula in D (default 4D+D), ranking |
| `config.py` | the teacher's YAML file (strict: an unknown key is an error) |
| `reveal.py` | colour map and pyBlindOpt reference runs (OBLESA start, fixed epochs) |
| `game.py` | the game as a service: joins, attempts, evaluation, reveal, board |
| `store.py` | SQLite persistence; player tokens stored as SHA-256 only |
| `server.py` | HTTP API (player identified by an HttpOnly cookie), WebSocket, static files |
| `__main__.py` | CLI: `--config`, `--db`, `--reset`, `--host`, `--port` |

| Method | Path | Purpose |
| :-- | :-- | :-- |
| `GET` | `/api/contest` | public facts: budget, number of problems, whether a code is needed |
| `POST` | `/api/join` | `{nickname, code}` → player cookie |
| `GET` | `/api/me` | the current attempt: progress and the player's own queries |
| `POST` | `/api/me/problems/{k}/eval` | `{x: [x1, x2]}` → f(x), remaining budget |
| `POST` | `/api/me/problems/{k}/stop` | end problem k early (after at least one evaluation) |
| `GET` | `/api/me/problems/{k}/reveal` | once problem k is over: the landscape, optimum and optimizers |
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
`contest.yaml` and set the functions (a count or a list, played in a shuffled
order), the budget formula in D (default `4D+D`), an optional join code,
`status: open|closed`, and the reveal (optimizers, runs, epochs). Leave `seed` out for a
fresh game at every start; set it to replay one.

Serve it on the local network, so students on the same network can reach the laptop:

```bash
venv/bin/python -m blindgame --config contest.yaml --host 0.0.0.0 --port 8000
```

The server first computes and stores every solution (a few seconds per function), then
serves. Students open `http://<laptop-ip>:8000`; the projector shows
`http://<laptop-ip>:8000/board`. Students who drop and come back resume where they were.
Restarting the server starts a new game, so everyone joins again. The database lives in the
system's temporary folder (`blindgame.db` in Python's `tempfile.gettempdir()`, usually a tmpfs
`/tmp`), so a reboot clears it for the next class; `--db` sets another file.

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
