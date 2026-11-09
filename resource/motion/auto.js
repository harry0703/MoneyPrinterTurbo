// Motion Studio engine: turns a storyboard (beats with a layout, timed to the voice) into frames.
// Render mode: auto.html?job=<url of the job folder>; the renderer awaits window.ready, calls
// window.init(words, env) and then window.render(t) for every frame.
// Preview mode: auto.html?preview=1 inside the studio; the parent page sends the character and text
// with postMessage and the page plays a short looping demo.
'use strict';
const params = new URLSearchParams(location.search);
const MOOD_MAP = { neutral: 'neutral', happy: 'happy', excited: 'rich', wink: 'wink', shocked: 'shocked', sad: 'crying' };
// Phosphor "bold" check and X (MIT), drawn as SVG so badges don't depend on system symbol fonts.
const ICON_PATH = {
  good: 'M232.49,80.49l-128,128a12,12,0,0,1-17,0l-56-56a12,12,0,1,1,17-17L96,183,215.51,63.51a12,12,0,0,1,17,17Z',
  bad: 'M208.49,191.51a12,12,0,0,1-17,17L128,145,64.49,208.49a12,12,0,0,1-17-17L111,128,47.51,64.49a12,12,0,0,1,17-17L128,111l63.51-63.52a12,12,0,0,1,17,17L145,128Z',
};
function toneIcon(tone) {
  if (!ICON_PATH[tone]) { const dot = document.createElement('span'); dot.className = 'dot'; return dot; }
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), path = document.createElementNS(ns, 'path');
  svg.setAttribute('viewBox', '0 0 256 256');
  path.setAttribute('d', ICON_PATH[tone]);
  svg.append(path);
  return svg;
}
let BEATS = [];

// ---------- text ----------
function box(cls, text, mark) {
  const outer = document.createElement('div'), inner = document.createElement('span');
  outer.className = `fit ${cls}`; inner.className = 't';
  const word = mark && text ? text.toLocaleLowerCase().indexOf(mark.toLocaleLowerCase()) : -1;
  if (word >= 0 && mark.length > 1) {
    const m = document.createElement('mark');
    m.textContent = text.slice(word, word + mark.length);
    inner.append(text.slice(0, word), m, text.slice(word + mark.length));
  } else inner.textContent = text || '';
  outer.append(inner);
  return outer;
}
const div = (cls) => { const d = document.createElement('div'); d.className = cls; return d; };

// Shrink the font until the text fits its fixed box; at the floor, let long words break.
// Measures the text's line boxes, not scrollHeight: Chrome counts tall glyph ascents (Baloo,
// Devanagari matras) as overflow, which would shrink big numbers far below what fits.
function fit(el, max, min = 26) {
  const inner = el.firstChild;
  let size = max;
  el.style.fontSize = `${size}px`;
  const over = () => inner.offsetHeight > el.clientHeight * 0.94 || inner.scrollWidth > el.clientWidth + 1;
  while (size > min && over()) { size -= 2; el.style.fontSize = `${size}px`; }
  if (over()) el.classList.add('wrap-any');
}

// "₹1,63,217", "42%", "3.5x": returns p -> text counting up from 0, or null when there is no number.
function counter(text) {
  const m = /^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$/s.exec(text || '');
  if (!m) return null;
  const [, pre, num, post] = m, target = parseFloat(num.replace(/,/g, ''));
  const decimals = (num.split('.')[1] || '').length;
  const locale = /\d,\d\d,\d{3}/.test(num) ? 'en-IN' : num.includes(',') ? 'en-US' : null;
  const fmt = { minimumFractionDigits: decimals, maximumFractionDigits: decimals };
  return (p) => pre + (locale ? (target * p).toLocaleString(locale, fmt) : (target * p).toFixed(decimals)) + post;
}

// ---------- layouts: each returns {node, fits: [[el, maxPx]], play(t)} ----------
const LAYOUTS = {
  hook(b) {
    const node = div('beat'), head = box('hook-head', b.headline);
    const kick = b.kicker && box(`hook-kick pop tone-${b.tone || 'good'}`, b.kicker);
    node.append(head, ...(kick ? [kick] : []));
    return {
      node, fits: [[head, 104], kick && [kick, 200]],
      play(t) {
        rise(head, t, b.start + 0.05, 0.45, 40);
        if (kick) {
          const at = b.emph ?? b.start + 0.6;
          pop(kick, t, at, 0.5);
          if (t > at + 0.5) kick.style.transform = `scale(${bump(t, at + 0.5, 0.4, 0.06)})`;
        }
      },
    };
  },

  big_number(b) {
    const node = div('beat'), label = box('big-label muted', b.label);
    const value = box(`big-value pop tone-${b.tone || 'good'}`, b.value), sub = b.headline && box('big-sub', b.headline);
    node.append(label, value, ...(sub ? [sub] : []));
    const count = counter(b.value), text = value.firstChild;
    return {
      node, fits: [[label, 60], [value, 250], sub && [sub, 72]],
      play(t) {
        const at = b.emph ?? b.start + 0.4;
        rise(label, t, b.start + 0.05, 0.4, 24);
        pop(value, t, at - 0.1, 0.45);
        if (count) text.textContent = count(outCubic(prog(t, at - 0.1, 0.9)));
        if (sub) rise(sub, t, at + 0.6, 0.45, 30);
      },
    };
  },

  compare(b) {
    const node = div('beat'), head = box('cmp-head', b.headline);
    const side = (s, cls) => {
      const card = div(`card ${cls}`), label = box('c-label muted', s.label), value = box(`c-value pop tone-${s.tone || 'neutral'}`, s.value);
      card.dataset.tone = s.tone || 'neutral'; card.append(label, value);
      return { card, label, value };
    };
    const L = side(b.left, 'cmp-left'), R = side(b.right, 'cmp-right');
    const kick = b.kicker && box(`cmp-kick kick tone-${b.tone || 'good'}`, b.kicker);
    node.append(head, L.card, R.card, ...(kick ? [kick] : []));
    const dur = b.end - b.start;
    return {
      node, fits: [[head, 76], [L.label, 42], [L.value, 120], [R.label, 42], [R.value, 120], kick && [kick, 56]],
      play(t) {
        rise(head, t, b.start + 0.05, 0.4, 30);
        pop(L.card, t, b.start + 0.35, 0.45);
        pop(R.card, t, b.emph ?? b.start + 0.45 * dur, 0.45);
        if (kick) pop(kick, t, b.start + 0.72 * dur, 0.45);
      },
    };
  },

  list(b) {
    const node = div('beat'), head = box('list-head', b.headline);
    node.append(head);
    const items = b.items.map((it, i) => {
      const row = div('item'), badge = div('badge'), text = box('', it.text);
      row.dataset.tone = it.tone || 'neutral'; row.style.top = `${410 + i * 138}px`;
      if (b.numbered) badge.textContent = String(i + 1);
      else badge.append(toneIcon(it.tone || 'neutral'));
      row.append(badge, text); node.append(row);
      return { row, text };
    });
    const dur = b.end - b.start, step = Math.min(1.6, (dur * 0.85 - 0.4) / items.length);
    return {
      node, fits: [[head, 76], ...items.map((it) => [it.text, 54])],
      play(t) {
        rise(head, t, b.start + 0.05, 0.4, 30);
        items.forEach((it, i) => rise(it.row, t, b.start + 0.4 + i * step, 0.4, 40));
      },
    };
  },

  statement(b) {
    const node = div('beat'), card = div('st-card'), text = box('', b.headline, b.emphasis);
    const kick = b.kicker && box('st-kick kick', b.kicker);
    card.append(text); node.append(...(kick ? [kick] : []), card);
    const mark = text.querySelector('mark');
    return {
      node, fits: [kick && [kick, 54], [text, 96]],
      play(t) {
        rise(card, t, b.start + 0.15, 0.45, 40);
        if (kick) pop(kick, t, b.start + 0.6, 0.4); // stamped onto the card once it has landed
        if (mark) mark.style.backgroundSize = `${100 * outCubic(prog(t, b.emph ?? b.start + 0.8, 0.35))}% 72%`;
      },
    };
  },

  outro(b) {
    const node = div('beat'), label = b.label && box('out-label muted', b.label), cta = box('out-cta kick', b.headline);
    node.append(...(label ? [label] : []), cta);
    return {
      node, fits: [label && [label, 50], [cta, 104]],
      play(t) {
        if (label) rise(label, t, b.start + 0.15, 0.4, 24);
        const at = b.emph ?? b.start + 0.5;
        pop(cta, t, at, 0.45);
        if (t > at + 0.45) cta.style.transform = `scale(${1 + 0.04 * Math.sin((t - at) * 7)})`;
      },
    };
  },
};

// ---------- storyboard -> stage ----------
function build(sb) {
  const root = $('beats');
  root.replaceChildren();
  BEATS = sb.beats.map((b, i) => {
    const view = (LAYOUTS[b.layout] || LAYOUTS.statement)(b);
    view.node.classList.add('scene'); view.node.id = `beat${i}`;
    root.append(view.node);
    return view;
  });
  $('stage').classList.toggle('no-host', !sb.character || sb.character.kind === 'none');
  document.documentElement.dataset.palette = sb.palette || 'lilac';
  scenes = sb.beats.map((b, i) => [`beat${i}`, b.start, i + 1 < sb.beats.length ? sb.beats[i + 1].start : b.end + 5]);
  moods = sb.beats.map((b) => [b.start, MOOD_MAP[b.mood] || 'neutral']);
  points = sb.beats.flatMap((b) => [b.start + 0.15, b.emph]).filter((x) => x != null).sort((a, z) => a - z);
}

const fitAll = () => { for (const v of BEATS) for (const f of v.fits) if (f) fit(f[0], f[1]); };

async function loadHost(character) {
  if (!character || character.kind === 'none') return;
  window.HOST_CONFIG = character;
  await import(character.kind === 'image' ? './host2d.js' : './host3d.js');
  await window.hostReady;
}

window.init = (words, env) => { W = words; window.ENV = env || []; phrases = phrasesFrom(W); };
window.render = (t) => {
  showScenes(t);
  for (const v of BEATS) v.play(t);
  host(t);
  renderCaptions($('cap'), t, phrases);
};

// ---------- preview mode ----------
function demo(msg) {
  const say = (msg.say || 'Hi! I will host your video. Add a topic and press Generate.').split(/\s+/).filter(Boolean);
  const words = say.map((text, i) => ({ text, start: 0.5 + i * 0.36, end: 0.5 + i * 0.36 + 0.3, br: i === say.length - 1 }));
  const end = words.at(-1).end, env = [];
  for (let f = 0; f < (end + 1.5) * FPS; f++) {
    const t = f / FPS, w = words.find((x) => t >= x.start && t < x.end);
    env.push(w ? 0.35 + 0.65 * Math.abs(Math.sin((t - w.start) * Math.PI / 0.15)) : 0);
  }
  const sb = { character: msg.character, beats: [{ layout: 'hook', headline: msg.title || 'Your title shows up here', kicker: msg.kicker || '',
    tone: 'good', mood: 'happy', start: 0, end: end + 1.5, emph: 0.9 }] };
  return { sb, words, env, duration: end + 1.5 };
}

function startPreview() {
  return new Promise((resolve) => {
    let started = false;
    addEventListener('message', async (e) => {
      if (e.origin !== location.origin || e.source !== parent || e.data?.type !== 'motion-preview') return;
      if (started) { // text-only update: rebuild the beat, keep the loaded character
        const d = demo(e.data); build(d.sb); fitAll(); return;
      }
      started = true;
      const d = demo(e.data);
      build(d.sb);
      await document.fonts.ready;
      fitAll();
      try { await loadHost(d.sb.character); } catch (err) { parent.postMessage({ type: 'motion-preview-error', message: String(err.message || err) }, location.origin); }
      window.init(d.words, d.env);
      moods = [[0, 'happy'], [1.8, 'neutral'], [2.8, 'wink']];
      const t0 = performance.now();
      const tick = (now) => { window.render(((now - t0) / 1000) % d.duration); requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
      parent.postMessage({ type: 'motion-preview-playing' }, location.origin);
      resolve();
    });
    parent.postMessage({ type: 'motion-preview-ready' }, location.origin);
  });
}

window.ready = (async () => {
  if (params.has('preview')) return startPreview();
  const job = params.get('job');
  const res = await fetch(`${job}/storyboard.json`);
  if (!res.ok) throw new Error(`storyboard.json: HTTP ${res.status}`);
  const sb = await res.json();
  build(sb);
  await document.fonts.ready;
  fitAll();
  await loadHost(sb.character);
})();
