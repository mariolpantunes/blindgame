// Student page: join a contest, then spend 5 evaluations per hidden problem.

// Student page: join, then play P1..Pn in order. After each problem's budget:
// its reveal (true colour map, your points, the optimizers, the optimum).
// After the last one: your summary and the live leaderboard. Reloading after
// finishing starts a practice attempt.

import { api, ApiError, el, fmt, standingHead, standingRows, watchBoard } from "./api.js";
import { fieldImage } from "./colormap.js";
import { PATH_COLORS, SpaceView } from "./space.js";

const $ = (id) => document.getElementById(id);
const state = {
  contest: null,
  me: null,
  mode: "play", // play | reveal | final
  problem: 0,
  reveals: {},
  selection: null,
  busy: false,
  repeatOk: false,
  closed: false,
  watching: null,
};

const view = new SpaceView($("space"), {
  onSelect: (x) => aim(x),
  onHover: (hit) => {
    const tip = $("tooltip");
    if (!hit) return tip.classList.add("hidden");
    tip.textContent = `#${hit.probe.seq}  f = ${fmt(hit.probe.f)}`;
    tip.style.left = `${hit.sx}px`;
    tip.style.top = `${hit.sy}px`;
    tip.classList.remove("hidden");
  },
  onCursor: (p) => {
    const inside = p && p[0] >= 0 && p[0] <= 1 && p[1] >= 0 && p[1] <= 1;
    $("cursor").textContent = !p ? "" : inside ? `x₁ ${p[0].toFixed(4)}   x₂ ${p[1].toFixed(4)}` : "outside the box";
  },
});

const n = () => state.contest.problems;
const budget = () => state.contest.budget;
const queries = (k = state.problem) => state.me.problems[k]?.queries ?? [];
const show = (id) => {
  for (const v of ["join-view", "game-view", "final-view"]) $(v).classList.toggle("hidden", v !== id);
};

function storage(key, value) {
  try {
    if (value === undefined) return sessionStorage.getItem(key);
    sessionStorage.setItem(key, String(value));
  } catch {
    /* storage unavailable: only a convenience */
  }
  return null;
}

// --- start and join ------------------------------------------------------------------

async function start() {
  state.contest = await api("GET", "/api/contest");
  state.closed = state.contest.status !== "open";
  document.title = `blindgame · ${state.contest.title}`;
  try {
    state.me = await api("GET", "/api/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return showJoin();
    throw e;
  }
  if (state.me.finished && !state.closed) state.me = await api("POST", "/api/me/restart");
  enter();
}

function showJoin() {
  show("join-view");
  $("join-title").textContent = state.contest.title;
  $("join-intro").textContent =
    `Somewhere in a dark box hides a minimum. ${state.contest.problems} problems, ` +
    `${state.contest.budget} evaluations each; every evaluation tells you a single number. Lowest value wins.`;
  $("code-label").classList.toggle("hidden", !state.contest.needs_code);
  const code = new URLSearchParams(location.search).get("c");
  if (code) $("join-code").value = code.toUpperCase();
  (state.contest.needs_code && !code ? $("join-code") : $("join-nick")).focus();
}

$("join-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("join-error").textContent = "";
  try {
    await api("POST", "/api/join", { nickname: $("join-nick").value, code: $("join-code").value });
    state.me = await api("GET", "/api/me");
    enter();
  } catch (err) {
    $("join-error").textContent = err.message;
  }
});

$("leave").addEventListener("click", async () => {
  await api("POST", "/api/leave");
  location.href = "/";
});

function enter() {
  const { me, contest } = state;
  $("contest-chip").textContent = contest.title;
  $("player-chip").textContent = me.player;
  $("practice-chip").textContent = `practice #${me.attempt - 1}`;
  $("practice-chip").classList.toggle("hidden", me.counts);
  for (const id of ["contest-chip", "player-chip", "leave"]) $(id).classList.remove("hidden");
  // One board socket per page, however many attempts are played in it.
  if (!state.watching) state.watching = watchBoard(onBoard);
  // Back from a reload: show the reveal of the last finished problem if it was not seen.
  const seen = Number(storage(`bg-seen-${me.attempt}`) ?? -1);
  if (me.finished) return showFinal();
  if (me.current > 0 && seen < me.current - 1) return showReveal(me.current - 1);
  showPlay(me.current);
}

// --- playing ---------------------------------------------------------------------------

function showPlay(k) {
  state.mode = "play";
  state.problem = k;
  show("game-view");
  $("play-panel").classList.remove("hidden");
  $("reveal-panel").classList.add("hidden");
  view.setReveal(null);
  view.setSeed(k + 1);
  view.reset();
  aim(null);
  render();
}

function aim(x) {
  state.selection = x;
  state.repeatOk = false;
  view.select(state.mode === "play" ? x : null);
  $("x1").value = x ? x[0].toFixed(6) : "";
  $("x2").value = x ? x[1].toFixed(6) : "";
  $("eval-error").textContent = "";
  updateButton();
}

for (const id of ["x1", "x2"]) {
  $(id).addEventListener("input", () => {
    const x = [Number($("x1").value), Number($("x2").value)];
    const ok = $("x1").value !== "" && $("x2").value !== "" && x.every((v) => v >= 0 && v <= 1);
    state.selection = ok ? x : null;
    state.repeatOk = false;
    view.select(state.selection);
    updateButton();
  });
}

function updateButton() {
  const locked = state.closed || state.mode !== "play" || queries().length >= budget();
  $("eval-btn").disabled = state.busy || locked || !state.selection;
  view.readOnly = locked;
  for (const id of ["x1", "x2"]) $(id).disabled = locked;
}

$("eval-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.selection || state.busy) return;
  const x = state.selection;
  const k = state.problem;
  if (queries(k).some((q) => q.x[0] === x[0] && q.x[1] === x[1]) && !state.repeatOk) {
    state.repeatOk = true;
    $("eval-error").textContent = "You already evaluated this exact point. Press Evaluate again to spend one anyway.";
    return;
  }
  state.busy = true;
  updateButton();
  try {
    const q = await api("POST", `/api/me/problems/${k}/eval`, { x });
    queries(k).push({ seq: q.seq, x: q.x, f: q.f });
    aim(null);
    if (q.remaining === 0) {
      state.me.current = k + 1;
      state.me.finished = k + 1 >= n();
      if (!state.me.finished) state.me.problems.push({ index: k + 1, queries: [] });
      state.busy = false;
      return showReveal(k);
    }
  } catch (err) {
    $("eval-error").textContent = err.message;
    if (err instanceof ApiError && err.status === 423) state.closed = true;
  } finally {
    state.busy = false;
    if (state.mode === "play") render();
  }
});

function renderProgress() {
  const current = state.me.current;
  $("progress").replaceChildren(
    ...Array.from({ length: n() }, (_, i) =>
      el("span", { class: i < current ? "done" : i === state.problem ? "now" : "", title: `problem ${i + 1}` }, i + 1),
    ),
  );
}

function render() {
  const k = state.problem;
  const qs = queries(k);
  renderProgress();
  $("stage-title").textContent = `Problem ${k + 1} of ${n()}`;
  view.setProbes(qs);
  $("budget").replaceChildren(
    ...Array.from({ length: budget() }, (_, i) => el("span", { class: `pip${i < qs.length ? " used" : ""}`, title: `evaluation ${i + 1}` })),
  );
  const best = qs.reduce((b, q) => (b === null || q.f < b.f ? q : b), null);
  $("best").textContent = best ? fmt(best.f) : "–";
  $("history").replaceChildren(
    ...qs.map((q) =>
      el(
        "tr",
        { class: `clickable${q === best ? " is-best" : ""}`, onclick: () => aim([...q.x]) },
        el("td", {}, q.seq),
        el("td", { class: "mono" }, q.x[0].toFixed(4)),
        el("td", { class: "mono" }, q.x[1].toFixed(4)),
        el("td", { class: "mono" }, fmt(q.f)),
      ),
    ),
  );
  let msg = "";
  if (state.closed) msg = "The contest is closed.";
  else if (!qs.length) msg = "Somewhere in this box hides a minimum. Click to aim.";
  $("banner").textContent = msg;
  $("banner").classList.toggle("hidden", !msg);
  updateButton();
}

// --- reveal ----------------------------------------------------------------------------

async function reveal(k) {
  if (!state.reveals[k]) state.reveals[k] = await api("GET", `/api/me/problems/${k}/reveal`);
  return state.reveals[k];
}

async function showReveal(k) {
  state.mode = "reveal";
  state.problem = k;
  show("game-view");
  aim(null);
  $("play-panel").classList.add("hidden");
  $("reveal-panel").classList.remove("hidden");
  renderProgress();
  $("stage-title").textContent = `Problem ${k + 1} of ${n()} · revealed`;
  const r = await reveal(k);
  storage(`bg-seen-${state.me.attempt}`, k);

  const paths = r.machines.map((m, i) => ({
    points: m.path.map((p) => p.x),
    color: PATH_COLORS[i % PATH_COLORS.length],
    on: true,
  }));
  const image = r.field.z ? fieldImage(r.field) : null;
  const redraw = () => view.setReveal(image, paths.filter((p) => p.on), r.x_opt);
  redraw();
  view.setProbes(r.you.points);
  view.reset();
  $("banner").textContent = `It was ${r.landscape}.`;
  $("banner").classList.remove("hidden");

  $("rv-name").textContent = r.landscape;
  $("rv-desc").textContent = r.description;
  $("rv-fopt").textContent = fmt(r.f_opt);
  $("rv-best").textContent = fmt(r.you.best);
  $("rv-gap").textContent = fmt(r.you.gap);
  $("rv-runs").textContent = String(state.contest.runs ?? "");
  $("rv-machines").replaceChildren(
    ...r.machines.map((m, i) =>
      el(
        "tr",
        {
          title: "Click to show or hide this optimizer's path",
          onclick: (e) => {
            paths[i].on = !paths[i].on;
            e.currentTarget.classList.toggle("off", !paths[i].on);
            redraw();
          },
        },
        el("td", {}, el("span", { class: "swatch", style: `background: ${PATH_COLORS[i % PATH_COLORS.length]}` }), m.name),
        el("td", { class: "mono" }, fmt(m.median_gap)),
        el("td", { class: "mono" }, `${Math.round(m.you_beat)}%`),
      ),
    ),
  );
  $("next-btn").textContent = k + 1 < n() ? "Next problem →" : "See my results →";
}

$("next-btn").addEventListener("click", () => {
  const k = state.problem + 1;
  if (k < n()) showPlay(k);
  else showFinal();
});

// --- final -----------------------------------------------------------------------------

async function showFinal() {
  state.mode = "final";
  show("final-view");
  $("final-title").textContent = state.me.counts ? "Your results" : `Your results (practice #${state.me.attempt - 1})`;
  const rows = [];
  for (let k = 0; k < n(); k++) {
    const r = await reveal(k);
    const best = r.machines.reduce((b, m) => (b === null || m.median_gap < b.median_gap ? m : b), null);
    rows.push(
      el(
        "tr",
        {},
        el("td", {}, `P${k + 1}`),
        el("td", {}, r.landscape),
        el("td", { class: "mono" }, fmt(r.you.gap)),
        el("td", {}, best ? `${best.name} (${fmt(best.median_gap)})` : "–"),
        el("td", { class: "mono" }, best ? `${Math.round(best.you_beat)}%` : "–"),
      ),
    );
  }
  $("final-rows").replaceChildren(...rows);
}

$("again-btn").addEventListener("click", async () => {
  state.me = await api("POST", "/api/me/restart");
  state.reveals = {};
  enter();
});

function onBoard(board) {
  $("lb-head").replaceChildren(standingHead(board));
  $("lb-rows").replaceChildren(...standingRows(board, state.me?.player));
  const closed = board.contest.status !== "open";
  if (closed !== state.closed) {
    state.closed = closed;
    if (state.mode === "play") render();
  }
}

start().catch((e) => {
  document.body.append(el("p", { class: "error", style: "padding: 16px" }, e.message));
});
