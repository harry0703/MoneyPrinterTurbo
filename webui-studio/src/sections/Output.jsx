import { ArrowCounterClockwise, ArrowRight, Check, Copy, DownloadSimple, X, YoutubeLogo } from '@phosphor-icons/react';
import { useId, useRef, useState } from 'react';
import { copyText } from '../api.js';
import { Notice, SectionHead } from '../ui.jsx';

const STAGES = [['writing', 'Writing the script'], ['voicing', 'Recording the voice'], ['rendering', 'Rendering the video']];
const ORDER = { queued: -1, writing: 0, voicing: 1, rendering: 2, done: 3 };
const ACTIVE = ['queued', 'writing', 'voicing', 'rendering'];

const eta = (s) => (s == null ? '' : s < 60 ? 'under a minute left' : `about ${Math.round(s / 60)} min left`);

function Stages({ job }) {
  const at = ORDER[job.status] ?? ORDER[job.stage] ?? -1;
  const stopped = job.status === 'failed' || job.status === 'cancelled';
  return (
    <ol className="stages">
      {STAGES.map(([id, label], i) => {
        const state = stopped && job.stage === id ? 'stopped' : at > i ? 'done' : at === i ? 'live' : 'todo';
        return (
          <li key={id} className={`stage-row is-${state}`}>
            <span className="stage-dot" aria-hidden="true">{state === 'done' && <Check size={14} weight="bold" />}{state === 'stopped' && <X size={14} weight="bold" />}</span>
            <span className="stage-label">{label}</span>
            {state === 'done' && <span className="stamp">Done</span>}
            {state === 'live' && id === 'rendering' && (
              <span className="stage-meter">
                <span className="meter" aria-hidden="true"><span style={{ transform: `scaleX(${job.progress || 0})` }} /></span>
                <span className="meter-text">{Math.round((job.progress || 0) * 100)}% of frames{job.eta_s != null ? `, ${eta(job.eta_s)}` : ''}</span>
              </span>
            )}
            {state === 'live' && id !== 'rendering' && <span className="stage-live">Working…</span>}
          </li>
        );
      })}
    </ol>
  );
}

// A read-only field with an inline copy button, the same shape as the API key row.
function KitField({ label, value, multiline }) {
  const id = useId();
  const [copied, setCopied] = useState(false);
  async function copy() {
    await copyText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="input-group">
        {multiline
          // rows sizes it where field-sizing: content isn't supported (Firefox, Safari)
          ? <textarea id={id} className="input kit-value" readOnly value={value}
            rows={Math.min(10, value.split('\n').reduce((n, line) => n + Math.max(1, Math.ceil(line.length / 56)), 0))} />
          : <input id={id} className="input" readOnly value={value} />}
        <button type="button" className={`icon-btn${copied ? ' is-copied' : ''}`} onClick={copy} aria-label={`Copy ${label.toLowerCase()}`}>
          {copied ? <Check size={20} weight="bold" aria-hidden="true" /> : <Copy size={20} weight="bold" aria-hidden="true" />}
        </button>
      </div>
      <span className="sr-only" aria-live="polite">{copied ? `${label} copied` : ''}</span>
    </div>
  );
}

function Done({ job, videoUrl, onStartOver }) {
  const [handedOff, setHandedOff] = useState(false);
  const link = useRef(null);
  const yt = job.result?.youtube ?? { title: job.title, description: '', hashtags: [] };
  const description = [yt.description, yt.hashtags.join(' ')].filter(Boolean).join('\n\n');
  // Only characters that filesystems reject become dashes, so Devanagari vowel signs survive.
  const filename = `${(job.title || 'short').replace(/[\s\\/:*?"<>|]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'short'}.mp4`;

  // YouTube has no way to receive a file or prefilled fields from another site, so hand over a kit:
  // open its uploader (inside the click, so it isn't blocked), copy the description, download the file.
  function toYouTube() {
    window.open('https://www.youtube.com/upload', '_blank', 'noopener');
    copyText(description).catch(() => {});
    link.current?.click();
    setHandedOff(true);
  }

  return (
    <>
      <SectionHead title="Your Short is ready">
        {job.result?.duration ? `${Math.round(job.result.duration)} seconds, 1080 × 1920. ` : ''}Watch it in the preview, then publish.
      </SectionHead>
      <div className="actions">
        <button type="button" className="btn btn-primary" disabled={!videoUrl} onClick={toYouTube}>
          <YoutubeLogo size={20} weight="fill" aria-hidden="true" /> Upload to YouTube
        </button>
        <a ref={link} className={`btn btn-secondary${videoUrl ? '' : ' is-disabled'}`} href={videoUrl || undefined} download={filename}>
          <DownloadSimple size={20} weight="bold" aria-hidden="true" /> Download MP4
        </a>
      </div>
      {handedOff && (
        <Notice title="YouTube Studio opened in a new tab">
          The video is downloading and the description is copied. In YouTube, drop the file in, paste the description, then copy the title from here.
        </Notice>
      )}
      <KitField label="Title" value={yt.title} />
      <KitField label="Description and hashtags" value={description} multiline />
      <div className="panel-foot">
        <button type="button" className="btn btn-quiet" onClick={onStartOver}><ArrowCounterClockwise size={18} weight="bold" aria-hidden="true" /> Make another video</button>
      </div>
    </>
  );
}

export function Output({ job, videoUrl, error, missing, busy, renderer, onGenerate, onCancel, onStartOver, onGo }) {
  if (job?.status === 'done') return <Done job={job} videoUrl={videoUrl} onStartOver={onStartOver} />;

  if (job && ACTIVE.includes(job.status)) {
    return (
      <>
        <SectionHead title="Making your Short">It takes a few minutes; keep this tab open or come back to it.</SectionHead>
        <Stages job={job} />
        <div className="panel-foot">
          <button type="button" className="btn btn-danger" onClick={onCancel}>Cancel</button>
        </div>
      </>
    );
  }

  const stopped = job && (job.status === 'failed' || job.status === 'cancelled');
  return (
    <>
      <SectionHead title={stopped ? 'The video wasn’t made' : 'Ready to generate'}>
        {stopped ? 'Nothing was lost: your brief and settings are still here.' : 'Check your choices, then generate. You can keep editing while it works.'}
      </SectionHead>
      {stopped && <Stages job={job} />}
      {(error || job?.status === 'failed') && <Notice tone="error" title="What went wrong">{error || job.message}</Notice>}
      {job?.status === 'cancelled' && <Notice title="Cancelled">You stopped this video before it finished.</Notice>}
      {!stopped && missing.length > 0 && (
        <ul className="todo">
          {missing.map(([section, text]) => (
            <li key={section}><button type="button" className="link-btn" onClick={() => onGo(section)}>{text}</button></li>
          ))}
        </ul>
      )}
      <div className="panel-foot">
        {stopped && <button type="button" className="btn btn-quiet" onClick={() => onGo('video')}>Edit the brief</button>}
        <button type="button" className="btn btn-primary" disabled={missing.length > 0 || busy || !renderer} onClick={onGenerate}>
          {stopped ? 'Try again' : 'Generate video'} <ArrowRight size={18} weight="bold" aria-hidden="true" />
        </button>
      </div>
    </>
  );
}
