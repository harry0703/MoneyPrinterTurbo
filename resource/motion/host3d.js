// Motion Studio 3D host: renders the character GLB into #host with three.js.
// Rig mode, for models with Chiku-style nodes (root, body, head, beak, jaw, eyeL, eyeR, wingL, wingR;
// optional Brow_L/R and Cheek_* meshes): the jaw follows the voice loudness every frame; head, eyes,
// brows and wings follow the script (word stress, phrases, moods, gesture points).
// Generic mode, for any other GLB: the model is fitted to the frame, plays its idle clip, and bobs,
// turns, squashes with the voice and reacts to moods.
// Reads window.HOST_CONFIG.url, the engine globals from lib.js and window.ENV; sets window.hostReady
// and window.hostRender.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const W_PX = 560, H_PX = 620;
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1); renderer.setSize(W_PX, H_PX);
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
document.getElementById('host').appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.55;
const key = new THREE.DirectionalLight(0xfff1dc, 2.4); key.position.set(-2.5, 4, 4);
const rim = new THREE.DirectionalLight(0xe9e0ff, 2.6); rim.position.set(2.6, 2.4, -3); // lilac, matches the stage
scene.add(key, rim, new THREE.HemisphereLight(0xf1ecff, 0x3a2f55, 0.8));
const cam = new THREE.PerspectiveCamera(26, W_PX / H_PX, 0.1, 50);
cam.position.set(0.9, 1.25, 5.6); cam.lookAt(0.05, 0.98, 0);

const RIG = ['root', 'body', 'head', 'beak', 'jaw', 'eyeL', 'eyeR', 'wingL', 'wingR'];
const P = {}, REST = {}, PUPILS = [], CHEEKS = [];
let mode = 'generic', fitted = null, mixer = null, idle = null;

window.hostReady = new GLTFLoader().loadAsync(window.HOST_CONFIG.url).then((g) => {
  const model = g.scene, drop = [];
  model.traverse((o) => {
    if (o.isLight || o.isCamera) drop.push(o);
    else if (o.isMesh && /floor|ground/i.test(o.name)) o.visible = false; // studio floors baked into exports
  });
  drop.forEach((o) => o.removeFromParent());
  if (RIG.every((n) => model.getObjectByName(n))) {
    mode = 'rig';
    scene.add(model);
    model.updateMatrixWorld(true);
    setupRig(model);
  } else {
    fitted = fitModel(model);
    scene.add(fitted);
    if (g.animations.length) {
      mixer = new THREE.AnimationMixer(model);
      idle = g.animations.find((a) => /idle|breath|stand/i.test(a.name)) || g.animations[0];
      mixer.clipAction(idle).play();
    }
  }
});

function setupRig(model) {
  for (const n of RIG) { P[n] = model.getObjectByName(n); REST[n] = { q: P[n].quaternion.clone(), p: P[n].position.clone() }; }
  // Gaze moves only iris + pupil inside each eye (turning the whole eye slides the white out of glasses).
  for (const eye of [P.eyeL, P.eyeR]) for (const o of eye.children) if (/iris|pupil/i.test(o.name)) PUPILS.push({ o, p: o.position.clone() });
  // Brow meshes may have their origin far from the face; give each a pivot at its own centre.
  for (const n of ['Brow_L', 'Brow_R']) {
    const brow = model.getObjectByName(n);
    if (!brow) continue;
    const pivot = new THREE.Group();
    pivot.position.copy(P.head.worldToLocal(new THREE.Box3().setFromObject(brow).getCenter(new THREE.Vector3())));
    P.head.add(pivot); pivot.updateMatrixWorld(true); pivot.attach(brow);
    P[n] = pivot; REST[n] = { q: pivot.quaternion.clone(), p: pivot.position.clone() };
  }
  model.traverse((o) => { if (o.isMesh && /^Cheek/i.test(o.name)) CHEEKS.push(o); });
}

// Scale any model to about 2 units tall (Chiku's size, which the camera frames), feet on the floor.
function fitModel(model) {
  const pivot = new THREE.Group();
  pivot.add(model);
  const size = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
  model.scale.multiplyScalar(2 / Math.max(size.y, size.x * 0.9, 1e-3));
  const b = new THREE.Box3().setFromObject(model), c = b.getCenter(new THREE.Vector3());
  model.position.sub(new THREE.Vector3(c.x, b.min.y, c.z));
  return pivot;
}

// ---------- helpers ----------
const clampTo = (x, a, b) => Math.min(b, Math.max(a, x));
const ease = (x) => 1 - (1 - clamp(x)) ** 3;
const qx = new THREE.Quaternion(), eul = new THREE.Euler();
function turn(n, x = 0, y = 0, z = 0) { // extra rotation from the rest pose, in the parent's space
  P[n].quaternion.copy(REST[n].q).premultiply(qx.setFromEuler(eul.set(x, y, z)));
}

// eye: overall eye scale; lid: 0 open .. 1 shut; wings: raise both (rad); pitch/roll: head (rad);
// brow: lift both brows; tilt: + raises the inner ends (worried/sad), - lowers them (determined);
// asym: + lifts the right brow and drops the left (sly, with the left-eye wink); blush: cheek size.
const MOODS = {
  neutral: { eye: 1, lid: 0, wink: 0, wings: 0.1, pitch: 0, roll: 0, jaw: 0, hop: 0, lean: 0, brow: 0, tilt: 0, asym: 0, blush: 1 },
  happy: { eye: 1, lid: 0.42, wink: 0, wings: 0.55, pitch: -0.08, roll: 0.07, jaw: 0.12, hop: 1, lean: 0, brow: 0.03, tilt: 0.05, asym: 0, blush: 1.25 },
  rich: { eye: 1.04, lid: 0.25, wink: 0, wings: 1.0, pitch: -0.12, roll: 0, jaw: 0.2, hop: 1.4, lean: 0, brow: 0.05, tilt: -0.12, asym: 0, blush: 1.3 },
  wink: { eye: 1, lid: 0.1, wink: 1, wings: 0.25, pitch: -0.04, roll: 0.17, jaw: 0.05, hop: 0.3, lean: 0, brow: 0.01, tilt: -0.05, asym: 0.04, blush: 1.15 },
  shocked: { eye: 1.1, lid: 0, wink: 0, wings: 1.25, pitch: 0.06, roll: 0, jaw: 0.38, hop: 0, lean: -0.14, brow: 0.09, tilt: 0.12, asym: 0, blush: 0.9 },
  crying: { eye: 0.94, lid: 0.55, wink: 0, wings: -0.2, pitch: 0.3, roll: -0.12, jaw: 0, hop: 0, lean: 0.06, brow: 0.02, tilt: 0.45, asym: 0, blush: 1 },
};

// Blinks at irregular 2.2-4.5 s gaps, deterministic so a re-render matches.
const BLINKS = []; for (let t = 1.1, k = 0; t < 600; k++) { BLINKS.push(t); t += 2.2 + 2.3 * hash01(k); }
const blinkAt = (t) => { const b = BLINKS.findLast((x) => x <= t); return b === undefined ? 0 : bell(t, b, 0.16); };
const stressOf = (w) => (window.ENV || [])[Math.floor(w.start * FPS) + 2] || 0;

// Head: slow drift, a nod on each stressed word, a fresh direction per phrase, a tilt on questions.
function headAt(t, m) {
  let yaw = 0.1 * Math.sin(0.63 * t) + 0.04 * Math.sin(1.7 * t + 1.3), pitch = 0.03 * Math.sin(1.1 * t + 2), roll = 0.04 * Math.sin(0.83 * t + 0.4);
  const wi = W.findLastIndex((w) => t >= w.start);
  if (wi >= 0) pitch += 0.07 * stressOf(W[wi]) * bell(t, W[wi].start, 0.32);
  const ph = phraseTurn(t);
  yaw += ph.turn * 0.34;
  if (ph.question) roll += 0.13 * ease((t - ph.since) / 0.4);
  return { yaw, pitch: pitch + m.pitch, roll: roll + m.roll };
}

// Brow flashes, as speakers do on emphasis: the loudest word of most phrases, and every question.
let FLASHES = null;
function flashAt(t) {
  FLASHES ??= phrases.flatMap((ph, pi) => {
    let best = ph.from;
    for (let i = ph.from; i <= ph.to; i++) if (stressOf(W[i]) > stressOf(W[best])) best = i;
    return W[ph.to].text.endsWith('?') || hash01(pi + 50) < 0.75 ? [W[best].start] : [];
  });
  const f = FLASHES.findLast((x) => x - 0.06 <= t);
  return f === undefined ? 0 : bell(t, f - 0.06, 0.45);
}

// Gestures on point cues, rotating through three: present with one wing, open both, point high.
function gestureAt(t) {
  const k = points.findLastIndex((p) => t >= p - 0.2);
  if (k < 0) return { l: 0, r: 0, look: 0, up: 0 };
  const p = points[k], amt = ease((t - p + 0.2) / 0.22) * (1 - ease((t - p - 0.9) / 0.4)), kind = k % 3;
  return kind === 0 ? { l: 0, r: 1.35 * amt, look: 0.22 * amt, up: 0 }
    : kind === 1 ? { l: 0.95 * amt, r: 0.95 * amt, look: 0, up: 0 }
    : { l: 0, r: 2.1 * amt, look: 0.3 * amt, up: 0.12 * amt };
}

function renderRig(t, m, open, g, h, pop, s) {
  const hop = m.hop * Math.abs(Math.sin(t * 7)) * 0.05;
  P.root.position.y = REST.root.p.y + 0.012 * Math.sin((2 * Math.PI * t) / 1.7) + hop + 0.06 * pop;
  P.root.scale.set(s, s * (1 - 0.04 * pop), s);
  turn('root', m.lean, 0.16, 0);
  turn('body', 0, 0, 0.03 * Math.sin(t * 1.3));
  turn('head', h.pitch - g.up, h.yaw + g.look, h.roll);
  turn('jaw', 0.75 * open + m.jaw); turn('beak', -0.14 * open - 0.12 * m.jaw);
  // eyes squash vertically for blinks and lids (depth stays 1 so they never poke through glasses)
  const blink = blinkAt(t);
  for (const [n, extra] of [['eyeL', m.wink], ['eyeR', 0]]) {
    const lid = clamp(Math.max(m.lid, extra, blink));
    P[n].scale.set(m.eye, m.eye * (1 - 0.9 * lid), 1);
  }
  const gx = clampTo(0.06 * (h.yaw + g.look) / 0.3, -0.03, 0.03), gy = 0.025 * (g.up / 0.12);
  for (const { o, p } of PUPILS) o.position.set(p.x + gx, p.y + gy, p.z);
  const lift = m.brow + 0.045 * flashAt(t) - 0.015 * blink;
  for (const [n, side] of [['Brow_L', -1], ['Brow_R', 1]]) {
    if (!P[n]) continue;
    P[n].position.y = REST[n].p.y + lift + side * m.asym;
    turn(n, 0, 0, -side * m.tilt);
  }
  for (const c of CHEEKS) c.scale.setScalar(m.blush);
  const flap = 0.08 * open * Math.sin(t * 18);
  turn('wingL', 0, 0, -(m.wings + g.l + flap));
  turn('wingR', 0, 0, m.wings + g.r + flap);
}

function renderGeneric(t, m, open, g, h, pop, s) {
  if (mixer) mixer.setTime(t % idle.duration); // absolute time: frames render in any order
  const hop = m.hop * Math.abs(Math.sin(t * 7)) * 0.05, sq = 0.035 * open;
  fitted.position.y = 0.015 * Math.sin((2 * Math.PI * t) / 1.7) + hop + 0.05 * pop;
  fitted.rotation.set(m.lean + 0.5 * (h.pitch - g.up), 0.16 + h.yaw + g.look, 0.5 * h.roll);
  fitted.scale.set(s * (1 - 0.4 * sq), s * (1 + sq) * (1 - 0.04 * pop), s * (1 - 0.4 * sq));
}

window.hostRender = (t) => {
  if (mode === 'rig' ? !P.root : !fitted) return;
  const m = blendMood(MOODS, t), open = voiceAt(t), g = gestureAt(t), h = headAt(t, m);
  const enter = clamp((t - 0.05) / 0.5), pop = bell(t, m.since, 0.35);
  const s = (enter < 1 ? 1 + 0.12 * Math.sin(Math.PI * enter) * (1 - enter) : 1) * ease(enter * 1.4); // entrance pop
  (mode === 'rig' ? renderRig : renderGeneric)(t, m, open, g, h, pop, s);
  renderer.render(scene, cam);
};
