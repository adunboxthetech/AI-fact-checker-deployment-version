/**
 * Mystical Cloud Animation — Canvas 2D port of the main app's WebGL shader.
 *
 * Renders the identical simplex-noise-based flowing cloud at reduced resolution
 * and scales up via CSS for performance.  Exposes the same intensity / loadingState
 * controls the main app uses so the popup can morph the cloud during fact-checks.
 */

/* ---------- simplex 2-D noise (Ashima Arts / Stefan Gustavson) ---------- */
const F2 = 0.5 * (Math.sqrt(3) - 1);
const G2 = (3 - Math.sqrt(3)) / 6;

// Permutation table (256 entries, doubled to avoid index wrapping)
const _p = [];
for (let i = 0; i < 256; i++) _p[i] = i;
for (let i = 255; i > 0; i--) {
  const j = Math.floor(Math.random() * (i + 1));
  [_p[i], _p[j]] = [_p[j], _p[i]];
}
const perm = new Uint8Array(512);
const permMod12 = new Uint8Array(512);
for (let i = 0; i < 512; i++) {
  perm[i] = _p[i & 255];
  permMod12[i] = perm[i] % 12;
}

const grad3 = [
  [1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],
  [1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],
  [0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1]
];

function snoise(xin, yin) {
  const s = (xin + yin) * F2;
  const i = Math.floor(xin + s);
  const j = Math.floor(yin + s);
  const t = (i + j) * G2;
  const X0 = i - t;
  const Y0 = j - t;
  const x0 = xin - X0;
  const y0 = yin - Y0;

  let i1, j1;
  if (x0 > y0) { i1 = 1; j1 = 0; }
  else          { i1 = 0; j1 = 1; }

  const x1 = x0 - i1 + G2;
  const y1 = y0 - j1 + G2;
  const x2 = x0 - 1.0 + 2.0 * G2;
  const y2 = y0 - 1.0 + 2.0 * G2;

  const ii = i & 255;
  const jj = j & 255;

  let n0 = 0, n1 = 0, n2 = 0;

  let t0 = 0.5 - x0*x0 - y0*y0;
  if (t0 >= 0) {
    const gi0 = permMod12[ii + perm[jj]];
    t0 *= t0;
    n0 = t0 * t0 * (grad3[gi0][0]*x0 + grad3[gi0][1]*y0);
  }

  let t1 = 0.5 - x1*x1 - y1*y1;
  if (t1 >= 0) {
    const gi1 = permMod12[ii + i1 + perm[jj + j1]];
    t1 *= t1;
    n1 = t1 * t1 * (grad3[gi1][0]*x1 + grad3[gi1][1]*y1);
  }

  let t2 = 0.5 - x2*x2 - y2*y2;
  if (t2 >= 0) {
    const gi2 = permMod12[ii + 1 + perm[jj + 1]];
    t2 *= t2;
    n2 = t2 * t2 * (grad3[gi2][0]*x2 + grad3[gi2][1]*y2);
  }

  return 70.0 * (n0 + n1 + n2); // range approx [-1, 1]
}

/* ---------- helpers (match GLSL) ---------- */
function smoothstep(edge0, edge1, x) {
  const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

function mix(a, b, t) { return a + (b - a) * t; }
function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

/* ---------- Cloud renderer ---------- */
class MysticalCloud {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { willReadFrequently: true });

    // Render at low resolution for performance, CSS scales up
    this.renderWidth  = 80;
    this.renderHeight = 100;
    this.canvas.width  = this.renderWidth;
    this.canvas.height = this.renderHeight;

    this.intensity    = 0.2;   // ambient = 0.2, loading = 1.0
    this.loadingState = 0.0;   // 0 = ambient, 1 = loading vortex
    this.startTime    = performance.now() / 1000;
    this._raf         = null;
    this._targetIntensity    = 0.2;
    this._targetLoadingState = 0.0;

    this.imageData = this.ctx.createImageData(this.renderWidth, this.renderHeight);

    this.start();
  }

  start() {
    const loop = () => {
      this._raf = requestAnimationFrame(loop);
      this._tweenValues();
      this._render();
    };
    loop();
  }

  stop() {
    if (this._raf) cancelAnimationFrame(this._raf);
  }

  /** Smoothly transition intensity and loadingState toward targets */
  _tweenValues() {
    const lerp = 0.04;
    this.intensity    += (this._targetIntensity    - this.intensity)    * lerp;
    this.loadingState += (this._targetLoadingState - this.loadingState) * lerp;
  }

  setIntensity(high) {
    this._targetIntensity = high ? 1.0 : 0.2;
  }

  setLoadingState(loading) {
    this._targetLoadingState = loading ? 1.0 : 0.0;
  }

  /** Main render — pixel-by-pixel port of the GLSL shader */
  _render() {
    const W = this.renderWidth;
    const H = this.renderHeight;
    const iTime = performance.now() / 1000 - this.startTime;
    const data = this.imageData.data;
    const aspect = W / H;
    const loadingState = this.loadingState;
    const intensity = this.intensity;

    const rotAngle = iTime * 0.8;
    const cosR = Math.cos(rotAngle);
    const sinR = Math.sin(rotAngle);
    const t = iTime * 0.3;

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const uvX = x / W;
        const uvY = y / H;

        // Centered UV (aspect-corrected x), shifted slightly lower to 0.65
        let cuvX = (uvX - 0.5) * aspect;
        let cuvY = uvY - 0.65;

        // Rotated UV (for loading vortex), pivoting around 0.65
        const ruvX = mix(uvX, cuvX * cosR - cuvY * sinR + 0.5, loadingState);
        const ruvY = mix(uvY, cuvX * sinR + cuvY * cosR + 0.65, loadingState);

        // Multilayer noise (same octaves as the shader)
        const n1 = snoise(ruvX * 1.5 + t,          ruvY * 1.5 + t * 0.5);
        const n2 = snoise(ruvX * 3.0 - t * 1.2,    ruvY * 3.0 - t * 0.8);
        const n3 = snoise(ruvX * 5.0 + t * 0.5,    ruvY * 5.0 - t);

        let n = n1 * 0.5 + n2 * 0.25 + n3 * 0.125;
        n = n * 0.5 + 0.5; // map to 0-1

        // Colors — Indigo → Purple → Ethereal White/Cyan
        const col1R = 0.28, col1G = 0.30, col1B = 0.84;
        const col2R = 0.46, col2G = 0.23, col2B = 0.86;
        const col3R = 0.85, col3G = 0.95, col3B = 1.00;

        const s1 = smoothstep(0.2, 0.8, n);
        let fR = mix(col1R, col2R, s1);
        let fG = mix(col1G, col2G, s1);
        let fB = mix(col1B, col2B, s1);

        const s2 = smoothstep(0.5, 1.0, n) * (0.5 + intensity * 0.5);
        fR = mix(fR, col3R, s2);
        fG = mix(fG, col3G, s2);
        fB = mix(fB, col3B, s2);

        // Distance from the new center
        const dist = Math.sqrt(cuvX * cuvX + cuvY * cuvY);

        // Ambient mask: soft, spread-out cloud centered around cuvY
        let ambientMask = smoothstep(0.60, 0.15, dist);
        ambientMask = Math.pow(ambientMask, 1.3) * (n * 0.6 + 0.4);

        // Loading mask: tighter circular vortex
        let loadingMask = smoothstep(0.35, 0.05, dist);
        loadingMask = Math.pow(loadingMask, 1.2) * (n * 0.7 + 0.3);

        const mask = mix(ambientMask, loadingMask, loadingState);
        const alpha = mask * mix(0.8, 1.0, loadingState);

        const idx = (y * W + x) * 4;
        data[idx]     = clamp(fR * 255, 0, 255) | 0;
        data[idx + 1] = clamp(fG * 255, 0, 255) | 0;
        data[idx + 2] = clamp(fB * 255, 0, 255) | 0;
        data[idx + 3] = clamp(alpha * 255, 0, 255) | 0;
      }
    }

    this.ctx.putImageData(this.imageData, 0, 0);
  }
}

/* ---------- Auto-initialise when DOM is ready ---------- */
let mysticalCloud = null;

document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("cloud-canvas");
  if (canvas) {
    mysticalCloud = new MysticalCloud(canvas);
  }
});
