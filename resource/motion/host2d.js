// Motion Studio image host: the uploaded picture as a talking sticker in #host.
// A transparent PNG stands on the disc as a cut-out; an opaque photo becomes a round portrait.
// One still image can't lip-sync, so it bounces and squashes with the voice loudness, tilts per
// phrase and reacts to moods. Reads window.HOST_CONFIG.url; sets window.hostReady and window.hostRender.
const wrap = document.createElement('div'), img = new Image();
wrap.className = 'img-host';
img.alt = '';
img.src = window.HOST_CONFIG.url;
wrap.append(img);
document.getElementById('host').append(wrap);

// Any clearly see-through pixel means the art was cut out already.
function hasTransparency(image) {
  const c = document.createElement('canvas');
  c.width = c.height = 48;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(image, 0, 0, 48, 48);
  const px = g.getImageData(0, 0, 48, 48).data;
  for (let i = 3; i < px.length; i += 4) if (px[i] < 200) return true;
  return false;
}

window.hostReady = img.decode().then(() => wrap.classList.add(hasTransparency(img) ? 'cutout' : 'portrait'));

// lift/hop in px, roll in degrees, size as a scale factor.
const MOODS = {
  neutral: { lift: 0, roll: 0, hop: 0, size: 1 },
  happy: { lift: 6, roll: 2, hop: 1, size: 1.02 },
  rich: { lift: 10, roll: 0, hop: 1.4, size: 1.04 },
  wink: { lift: 2, roll: 6, hop: 0.3, size: 1.01 },
  shocked: { lift: 22, roll: 0, hop: 0, size: 1.07 },
  crying: { lift: -10, roll: -5, hop: 0, size: 0.97 },
};

window.hostRender = (t) => {
  const m = blendMood(MOODS, t), open = voiceAt(t), ph = phraseTurn(t);
  const enter = 1 - (1 - clamp((t - 0.05) / 0.45)) ** 3, pop = bell(t, m.since, 0.35);
  const y = 6 * Math.sin((2 * Math.PI * t) / 1.7) + m.hop * 18 * Math.abs(Math.sin(t * 7)) + 14 * pop + m.lift;
  const roll = 7 * ph.turn + m.roll + 1.5 * Math.sin(t * 0.9) + (ph.question ? 4 : 0);
  const sq = 0.05 * open, s = m.size * enter;
  wrap.style.transform = `translateY(${-y}px) rotate(${roll}deg) scale(${s * (1 - 0.4 * sq)}, ${s * (1 + sq)})`;
};
