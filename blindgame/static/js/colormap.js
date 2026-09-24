// Viridis, sampled at 9 stops and linearly interpolated (as in pyOptViewer).
const STOPS = [
  [68, 1, 84], [71, 44, 122], [59, 81, 139], [44, 113, 142], [33, 144, 141],
  [39, 173, 129], [92, 200, 99], [170, 220, 50], [253, 231, 37],
];

export function viridis(v) {
  const x = Math.min(Math.max(v, 0), 1) * (STOPS.length - 1);
  const i = Math.min(Math.floor(x), STOPS.length - 2);
  const f = x - i;
  const a = STOPS[i], b = STOPS[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

// Maps values to [0, 1] on a log scale: spreads the low end, where the optimum lives.
export function normaliser(zMin, zMax) {
  const d = Math.log1p(zMax - zMin || 1);
  return (z) => Math.log1p(Math.max(z - zMin, 0)) / d;
}

// The landscape as an image: pixel row r is y = 1 - r / (n - 1) (y points up).
export function fieldImage(field) {
  const n = field.resolution;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = n;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(n, n);
  const norm = normaliser(field.z_min, field.z_max);
  for (let r = 0; r < n; r++) {
    const row = field.z[n - 1 - r];
    for (let c = 0; c < n; c++) {
      const [R, G, B] = viridis(norm(row[c]));
      const k = 4 * (r * n + c);
      img.data[k] = R;
      img.data[k + 1] = G;
      img.data[k + 2] = B;
      img.data[k + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}
