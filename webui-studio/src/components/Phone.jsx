import { useEffect, useRef, useState } from 'react';

const ACTIVE = ['queued', 'writing', 'voicing', 'rendering'];
const STAGE_LABEL = { queued: 'Waiting in the queue', writing: 'Writing the script', voicing: 'Recording the voice', rendering: 'Rendering frames' };
const DEMO_SAY = 'Hi! I will host your video. Watch my mouth follow the voice.';

const minutes = (s) => (s == null ? '' : s < 60 ? 'under a minute left' : `about ${Math.round(s / 60)} min left`);

// The phone runs the real scene engine (/motion-engine/auto.html?preview=1), so the character and
// title look exactly as they will in the video. While a job runs the engine is unloaded to leave the
// CPU to the server's renderer, and the finished video replaces it.
export function Phone({ character, title, job, videoUrl, error, setError }) {
  const boxRef = useRef(null);
  const frameRef = useRef(null);
  const [scale, setScale] = useState(1 / 3);
  const [ready, setReady] = useState(false);
  const charKey = `${character.kind}:${character.url}`;
  const running = Boolean(job && ACTIVE.includes(job.status));
  const showVideo = job?.status === 'done' && videoUrl;

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setScale(entry.contentRect.width / 1080));
    observer.observe(boxRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => { setReady(false); setError(''); }, [charKey]); // eslint-disable-line react-hooks/exhaustive-deps
  // The engine unmounts while a job runs or a video shows; its next mount must wait for a fresh "ready".
  useEffect(() => { if (running || showVideo) setReady(false); }, [running, showVideo]);

  useEffect(() => {
    function onMessage(event) {
      if (event.origin !== window.location.origin || event.source !== frameRef.current?.contentWindow) return;
      if (event.data?.type === 'motion-preview-ready') setReady(true);
      if (event.data?.type === 'motion-preview-error') setError(`The preview couldn't load this character: ${event.data.message}`);
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [setError]);

  // First message starts the demo with the character; later ones only update the title card.
  useEffect(() => {
    if (!ready) return undefined;
    const timer = setTimeout(() => {
      frameRef.current?.contentWindow?.postMessage(
        { type: 'motion-preview', character: { kind: character.kind, url: character.url }, title: title.trim(), say: DEMO_SAY },
        window.location.origin,
      );
    }, 220);
    return () => clearTimeout(timer);
  }, [ready, title, charKey]); // eslint-disable-line react-hooks/exhaustive-deps

  let caption = 'Live preview: your character and title';
  if (running) caption = job.status === 'rendering' ? `Rendering, ${minutes(job.eta_s) || 'starting'}` : STAGE_LABEL[job.status];
  if (showVideo) caption = `Your video${job.result?.duration ? `, ${Math.round(job.result.duration)} s` : ''}`;

  return (
    <aside className="stage" aria-label="Preview">
      <div className="phone">
        <div className="phone-screen" ref={boxRef}>
          {showVideo ? (
            <video className="phone-video" src={videoUrl} controls playsInline autoPlay muted />
          ) : running ? (
            <div className="phone-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={Math.round((job.overall || 0) * 100)} aria-label="Video progress">
              <span className="phone-pct">{Math.round((job.overall || 0) * 100)}%</span>
              <span className="phone-stage">of the whole video</span>
              <span className="phone-sub">Now: {STAGE_LABEL[job.status].toLowerCase()}</span>
            </div>
          ) : (
            <iframe key={charKey} ref={frameRef} className="phone-frame" title="Live preview of the video"
              src="/motion-engine/auto.html?preview=1" style={{ transform: `scale(${scale})` }} tabIndex={-1} />
          )}
        </div>
      </div>
      <p className={`stage-caption${error ? ' is-error' : ''}`} aria-live="polite">{error || caption}</p>
    </aside>
  );
}
