// Motion Studio engine: timeline and host helpers shared by auto.js, host3d.js and host2d.js.
// Classic script: everything here is a page global.
const $ = (id) => document.getElementById(id);
const FPS = 30;
const clamp = (x) => Math.max(0, Math.min(1, x));
const prog = (t, a, d) => clamp((t - a) / d);
const outCubic = (x) => 1 - (1 - x) ** 3;
const outBack = (x) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2; };
const set = (el, o, tf = '') => { el.style.opacity = o; el.style.transform = tf; };
const pop = (el, t, t0, d = 0.45) => { const p = prog(t, t0, d); set(el, clamp(p * 3), `scale(${0.6 + 0.4 * outBack(p)})`); };
const rise = (el, t, t0, d = 0.5, dy = 40) => { const p = outCubic(prog(t, t0, d)); set(el, p, `translateY(${(1 - p) * dy}px)`); };
const bump = (t, t0, d = 0.4, amt = 0.12) => 1 + amt * Math.sin(Math.PI * prog(t, t0, d));
const bell = (t, t0, d) => Math.sin(Math.PI * clamp((t - t0) / d)); // 0 -> 1 -> 0 over d seconds
const hash01 = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

// Spoken words [{text, start, end, br?}] and caption phrases; set by auto.js init().
let W = [], phrases = [];

// Caption phrases break where the script has punctuation (w.br), or at spoken pauses when that is
// missing; long phrases are capped at maxLen words.
function phrasesFrom(words, gap = 0.2, maxLen = 6) {
  const out = [], hasBreaks = words.some((w) => 'br' in w); let from = 0;
  words.forEach((w, i) => {
    const next = words[i + 1], pause = hasBreaks ? w.br : next && next.start - w.end > gap;
    if (!next || pause || i - from + 1 >= maxLen) { out.push({ from, to: i }); from = i + 1; }
  });
  return out;
}

// Words come from AI-written text, so captions are built with textContent, never innerHTML.
function renderCaptions(el, t, list) {
  const cur = list.findLast((ph) => t >= W[ph.from].start - 0.05);
  if (!cur || t > W[cur.to].end + 0.6) { el.replaceChildren(); return; }
  const spans = W.slice(cur.from, cur.to + 1).map((w, k) => {
    const i = cur.from + k, s = document.createElement('span');
    s.textContent = w.text;
    if (t >= w.start && (i === cur.to || t < W[i + 1].start)) s.className = 'on';
    return s;
  });
  el.replaceChildren(...spans);
}

// ---------- Stage: beat fades, moods and gesture cues (filled by auto.js) ----------
// scenes [[id, start, end]], moods [[t, mood]], points [t] (moments the host gestures at the screen).
let scenes = [], moods = [], points = [];

function showScenes(t) {
  for (const [id, a, b] of scenes) {
    const o = outCubic(prog(t, a, 0.3)) * (1 - outCubic(prog(t, b - 0.2, 0.3)));
    const el = $(id); el.style.opacity = o; el.style.visibility = o > 0 ? 'visible' : 'hidden';
  }
}

// ---------- Host helpers ----------
// Mouth opening from the voice: loudness of this and the next frame (mouths lead sound slightly).
// window.ENV is the per-frame loudness (0..1) that the renderer passes to init().
function voiceAt(t) {
  const env = window.ENV || [], i = Math.floor(t * FPS), v = Math.max(env[i] || 0, env[i + 1] || 0);
  return v < 0.08 ? 0 : clamp((v - 0.08) / 0.72) ** 0.8;
}

// Mood parameters blended from the previous mood over 0.3 s, plus the time the current mood began.
function blendMood(table, t) {
  const i = moods.findLastIndex((m) => t >= m[0]), cur = moods[Math.max(i, 0)] || [0, 'neutral'];
  const prev = moods[Math.max(i - 1, 0)] || cur;
  const a = table[prev[1]] || table.neutral, b = table[cur[1]] || table.neutral;
  const k = 1 - (1 - clamp((t - cur[0]) / 0.3)) ** 3, out = { since: cur[0] };
  for (const key of Object.keys(table.neutral)) out[key] = a[key] + (b[key] - a[key]) * k;
  return out;
}

// A fresh direction (-0.4..0.6) per caption phrase, eased in over 0.45 s, so turns follow the speech.
function phraseTurn(t) {
  const pi = phrases.findLastIndex((ph) => t >= W[ph.from].start - 0.1);
  if (pi < 0) return { turn: 0, question: false, since: 0 };
  const ph = phrases[pi], k = 1 - (1 - clamp((t - W[ph.from].start + 0.1) / 0.45)) ** 3;
  const prev = pi > 0 ? hash01(pi - 1) - 0.4 : 0;
  return { turn: prev + (hash01(pi) - 0.4 - prev) * k, question: W[ph.to].text.endsWith('?'), since: W[ph.from].start };
}

function host(t) { window.hostRender?.(t); }
