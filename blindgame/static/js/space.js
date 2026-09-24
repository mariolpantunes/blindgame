// The player's view of the search space: dark, starry, and empty except for
// the points they paid for. While playing nothing about the landscape is drawn;
// probes are coloured by their rank among the player's own values, never by f.
// In reveal mode the box shows the true colour map, the optimizers' paths and
// the optimum.

const BOX_FILL = "rgba(136, 192, 208, 0.035)";
const BOX_EDGE = "rgba(136, 192, 208, 0.35)";
const OUTSIDE = "rgba(0, 0, 0, 0.35)";
const SELECT = "#eceff4";
// Best → worst: gold, teal, dim blue.
const RAMP = [
  [235, 203, 139],
  [136, 192, 208],
  [94, 129, 172],
];
const HIT_PX = 12;
// Optimizer paths in the reveal (Nord aurora + frost).
export const PATH_COLORS = ["#bf616a", "#d08770", "#b48ead", "#a3be8c", "#88c0d0", "#ebcb8b", "#5e81ac"];

function mulberry32(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function ramp(t) {
  const s = t * (RAMP.length - 1);
  const i = Math.min(Math.floor(s), RAMP.length - 2);
  const u = s - i;
  return RAMP[i].map((c, k) => Math.round(c + (RAMP[i + 1][k] - c) * u));
}

export class SpaceView {
  constructor(canvas, { onSelect, onHover, onCursor }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.onCursor = onCursor;
    this.probes = [];
    this.selection = null;
    this.field = null; // reveal: an image of the landscape over the box
    this.paths = []; // reveal: [{start: [[x, y]...], trail: [[x, y]...], best: [x, y], color}]
    this.optimum = null; // reveal: [x, y]
    this.readOnly = false;
    this.view = { cx: 0.5, cy: 0.5, scale: 1 };
    this.fitScale = 1;
    this.drag = null;
    this.pending = false;
    this.setSeed(1);

    new ResizeObserver(() => this._resize()).observe(canvas.parentElement);
    canvas.addEventListener("pointerdown", (e) => this._down(e));
    canvas.addEventListener("pointermove", (e) => this._move(e));
    canvas.addEventListener("pointerup", (e) => this._up(e));
    canvas.addEventListener("pointerleave", () => {
      this.onHover(null);
      this.onCursor(null);
    });
    canvas.addEventListener("wheel", (e) => this._wheel(e), { passive: false });
    canvas.addEventListener("dblclick", () => this.reset());
  }

  // A different sky per problem, so problems do not look alike.
  setSeed(seed) {
    const rnd = mulberry32(seed * 7919 + 17);
    this.near = Array.from({ length: 700 }, () => ({
      x: -2 + 5 * rnd(),
      y: -2 + 5 * rnd(),
      r: 0.3 + rnd() * 0.9,
      a: 0.15 + rnd() * 0.5,
    }));
    this.far = Array.from({ length: 260 }, () => ({
      x: rnd(),
      y: rnd(),
      r: 0.3 + rnd() * 0.5,
      a: 0.08 + rnd() * 0.25,
    }));
    this.draw();
  }

  setProbes(probes) {
    const order = [...probes].sort((a, b) => a.f - b.f);
    const n = order.length;
    this.probes = probes.map((p) => {
      const rank = order.indexOf(p);
      return { ...p, rank, t: n > 1 ? rank / (n - 1) : 0 };
    });
    this.draw();
  }

  // Reveal mode: pass null to go back to the dark box.
  setReveal(field, paths = [], optimum = null) {
    this.field = field;
    this.paths = paths;
    this.optimum = optimum;
    this.draw();
  }

  select(point) {
    this.selection = point;
    this.draw();
  }

  reset() {
    this.view = { cx: 0.5, cy: 0.5, scale: this.fitScale };
    this.draw();
  }

  // --- coordinates --------------------------------------------------------------------

  toScreen(x, y) {
    const { cx, cy, scale } = this.view;
    return [this.w / 2 + (x - cx) * scale, this.h / 2 - (y - cy) * scale];
  }

  toWorld(sx, sy) {
    const { cx, cy, scale } = this.view;
    return [cx + (sx - this.w / 2) / scale, cy - (sy - this.h / 2) / scale];
  }

  _local(e) {
    const r = this.canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  // --- interaction --------------------------------------------------------------------

  _down(e) {
    const [sx, sy] = this._local(e);
    this.drag = { sx, sy, cx: this.view.cx, cy: this.view.cy, moved: false };
    this.canvas.setPointerCapture(e.pointerId);
  }

  _move(e) {
    const [sx, sy] = this._local(e);
    if (this.drag) {
      const dx = sx - this.drag.sx;
      const dy = sy - this.drag.sy;
      if (Math.hypot(dx, dy) > 4) {
        this.drag.moved = true;
        this.canvas.classList.add("grabbing");
      }
      if (this.drag.moved) {
        this.view.cx = this.drag.cx - dx / this.view.scale;
        this.view.cy = this.drag.cy + dy / this.view.scale;
        this.draw();
      }
    }
    const [x, y] = this.toWorld(sx, sy);
    this.onCursor([x, y]);
    const hit = this._hit(sx, sy);
    this.onHover(hit ? { probe: hit, sx, sy } : null);
  }

  _up(e) {
    const drag = this.drag;
    this.drag = null;
    this.canvas.classList.remove("grabbing");
    if (!drag || drag.moved || this.readOnly) return;
    const [sx, sy] = this._local(e);
    const hit = this._hit(sx, sy);
    const [x, y] = hit ? hit.x : this.toWorld(sx, sy);
    this.onSelect([Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))]);
  }

  _wheel(e) {
    e.preventDefault();
    const [sx, sy] = this._local(e);
    const [wx, wy] = this.toWorld(sx, sy);
    const factor = Math.exp(-e.deltaY * 0.0015);
    const scale = Math.min(this.fitScale * 5000, Math.max(this.fitScale * 0.4, this.view.scale * factor));
    // Keep the point under the cursor fixed.
    this.view.scale = scale;
    this.view.cx = wx - (sx - this.w / 2) / scale;
    this.view.cy = wy + (sy - this.h / 2) / scale;
    this.draw();
  }

  _hit(sx, sy) {
    let best = null;
    let dist = HIT_PX;
    for (const p of this.probes) {
      const [px, py] = this.toScreen(p.x[0], p.x[1]);
      const d = Math.hypot(px - sx, py - sy);
      if (d < dist) {
        dist = d;
        best = p;
      }
    }
    return best;
  }

  _resize() {
    const r = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.w = r.width;
    this.h = r.height;
    this.canvas.width = Math.round(r.width * dpr);
    this.canvas.height = Math.round(r.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const fit = Math.min(r.width, r.height) / 1.25;
    if (this.view.scale === this.fitScale) this.view.scale = fit;
    this.fitScale = fit;
    this.draw();
  }

  // --- drawing ------------------------------------------------------------------------

  draw() {
    if (this.pending) return;
    this.pending = true;
    requestAnimationFrame(() => {
      this.pending = false;
      this._draw();
    });
  }

  _draw() {
    const { ctx, w, h } = this;
    if (!w || !h) return;
    ctx.clearRect(0, 0, w, h);

    // Far stars drift slowly with panning (parallax), ignoring zoom.
    const { cx, cy } = this.view;
    for (const s of this.far) {
      const x = (((s.x - cx * 0.05) % 1) + 1) % 1;
      const y = (((s.y + cy * 0.05) % 1) + 1) % 1;
      ctx.fillStyle = `rgba(216, 222, 233, ${s.a})`;
      ctx.beginPath();
      ctx.arc(x * w, y * h, s.r, 0, 2 * Math.PI);
      ctx.fill();
    }
    // Near stars live in world coordinates: they move and spread as you zoom.
    for (const s of this.near) {
      if (this.field && s.x >= 0 && s.x <= 1 && s.y >= 0 && s.y <= 1) continue;
      const [x, y] = this.toScreen(s.x, s.y);
      if (x < -2 || y < -2 || x > w + 2 || y > h + 2) continue;
      ctx.fillStyle = `rgba(216, 222, 233, ${s.a})`;
      ctx.beginPath();
      ctx.arc(x, y, s.r, 0, 2 * Math.PI);
      ctx.fill();
    }

    // The box: slightly lit inside, darkened outside.
    const [x0, y1] = this.toScreen(0, 0);
    const [x1, y0] = this.toScreen(1, 1);
    ctx.fillStyle = OUTSIDE;
    ctx.beginPath();
    ctx.rect(0, 0, w, h);
    ctx.rect(x0, y0, x1 - x0, y1 - y0);
    ctx.fill("evenodd");
    ctx.fillStyle = BOX_FILL;
    ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
    if (this.field) {
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(this.field, x0, y0, x1 - x0, y1 - y0);
    }
    ctx.setLineDash([6, 6]);
    ctx.strokeStyle = BOX_EDGE;
    ctx.lineWidth = 1;
    ctx.strokeRect(x0 + 0.5, y0 + 0.5, x1 - x0, y1 - y0);
    ctx.setLineDash([]);

    // Optimizers: initial population (hollow circles), best-so-far trail (line with
    // a dark casing, so it reads on any colour of the map) and final best (diamond).
    for (const path of this.paths) {
      ctx.strokeStyle = path.color;
      ctx.lineWidth = 1.5;
      for (const [x, y] of path.start) {
        const [px, py] = this.toScreen(x, y);
        ctx.beginPath();
        ctx.arc(px, py, 3.5, 0, 2 * Math.PI);
        ctx.stroke();
      }
      const trail = path.trail.map(([x, y]) => this.toScreen(x, y));
      for (const [width, color] of [
        [5, "rgba(46, 52, 64, 0.85)"],
        [2.5, path.color],
      ]) {
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.lineJoin = "round";
        ctx.beginPath();
        trail.forEach(([px, py], k) => (k === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)));
        ctx.stroke();
      }
      ctx.fillStyle = path.color;
      for (const [px, py] of trail) {
        ctx.beginPath();
        ctx.arc(px, py, 2.5, 0, 2 * Math.PI);
        ctx.fill();
      }
      const [bx, by] = this.toScreen(path.best[0], path.best[1]);
      ctx.beginPath();
      ctx.moveTo(bx, by - 9);
      ctx.lineTo(bx + 7, by);
      ctx.lineTo(bx, by + 9);
      ctx.lineTo(bx - 7, by);
      ctx.closePath();
      ctx.fillStyle = path.color;
      ctx.fill();
      ctx.strokeStyle = "#eceff4";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Probes, worst first so the best is on top.
    const sorted = [...this.probes].sort((a, b) => b.rank - a.rank);
    for (const p of sorted) {
      const [px, py] = this.toScreen(p.x[0], p.x[1]);
      // In the reveal the colour map owns the colours: probes turn white.
      const [r, g, b] = this.field ? [236, 239, 244] : ramp(p.t);
      const glow = ctx.createRadialGradient(px, py, 0, px, py, 22);
      glow.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.55)`);
      glow.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(px, py, 22, 0, 2 * Math.PI);
      ctx.fill();
      ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, 2 * Math.PI);
      ctx.fill();
      if (p.rank === 0) {
        ctx.strokeStyle = `rgb(${r}, ${g}, ${b})`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(px, py, 10, 0, 2 * Math.PI);
        ctx.stroke();
      }
      ctx.fillStyle = "#eceff4";
      ctx.font = "600 11px system-ui, sans-serif";
      ctx.fillText(String(p.seq), px + 9, py - 9);
    }

    // The optimum: a star.
    if (this.optimum) {
      const [ox, oy] = this.toScreen(this.optimum[0], this.optimum[1]);
      ctx.beginPath();
      for (let k = 0; k < 10; k++) {
        const r = k % 2 ? 5 : 12;
        const a = -Math.PI / 2 + (k * Math.PI) / 5;
        ctx.lineTo(ox + r * Math.cos(a), oy + r * Math.sin(a));
      }
      ctx.closePath();
      ctx.fillStyle = "#eceff4";
      ctx.fill();
      ctx.strokeStyle = "#bf616a";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // The point about to be evaluated.
    if (this.selection) {
      const [sx, sy] = this.toScreen(this.selection[0], this.selection[1]);
      ctx.strokeStyle = SELECT;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(sx, sy, 9, 0, 2 * Math.PI);
      for (const [dx, dy] of [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
      ]) {
        ctx.moveTo(sx + dx * 5, sy + dy * 5);
        ctx.lineTo(sx + dx * 16, sy + dy * 16);
      }
      ctx.stroke();
    }
  }
}
