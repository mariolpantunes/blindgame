// Thin fetch wrapper: JSON in, JSON out, errors carry the server's `detail`.

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
  }
}

export async function api(method, path, body, headers = {}) {
  const res = await fetch(path, {
    method,
    headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    let detail = data?.detail ?? res.statusText;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    throw new ApiError(res.status, detail);
  }
  return data;
}

// Reconnecting WebSocket for the live leaderboard.
export function watchBoard(onBoard) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let socket;
  let closed = false;
  const connect = () => {
    socket = new WebSocket(`${proto}://${location.host}/ws/board`);
    socket.onmessage = (e) => onBoard(JSON.parse(e.data));
    socket.onclose = (e) => {
      if (!closed) setTimeout(connect, 2000);
    };
  };
  connect();
  return () => {
    closed = true;
    socket.close();
  };
}

// Values span many orders of magnitude; keep the table readable.
export function fmt(f) {
  if (f === null || f === undefined) return "–";
  const a = Math.abs(f);
  if (a !== 0 && (a >= 1e7 || a < 1e-3)) return f.toExponential(4);
  return f.toFixed(4);
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c !== null && c !== undefined && c !== false) node.append(c instanceof Node ? c : String(c));
  }
  return node;
}

// Leaderboard rows: competition places (1, 2, 2, 4), optional highlight.
export function standingRows(board, me = null) {
  let place = 0;
  return board.standings.map((s, i) => {
    if (i === 0 || s.total !== board.standings[i - 1].total) place = i + 1;
    return el(
      "tr",
      { class: s.player === me ? "is-me" : "" },
      el("td", {}, place),
      el("td", { class: "name" }, s.player),
      el("td", { class: "mono" }, el("strong", {}, s.total)),
      s.ranks.map((r) => el("td", { class: "mono" }, r)),
      el("td", { class: "mono" }, `${s.done}/${board.contest.problems}`),
    );
  });
}

export function standingHead(board) {
  const problems = Array.from({ length: board.contest.problems }, (_, i) => el("th", {}, `P${i + 1}`));
  return el("tr", {}, el("th", {}, "#"), el("th", { class: "name" }, "Player"), el("th", {}, "Score"), problems, el("th", {}, "Done"));
}
