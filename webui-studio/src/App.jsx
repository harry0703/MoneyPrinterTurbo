import { useEffect, useRef, useState } from 'react';
import { ApiError, api, serverKey } from './api.js';
import { Phone } from './components/Phone.jsx';
import { Rail } from './components/Rail.jsx';
import { Brief } from './sections/Brief.jsx';
import { Character } from './sections/Character.jsx';
import { Output } from './sections/Output.jsx';
import { Writer } from './sections/Writer.jsx';
import { Field, Notice } from './ui.jsx';

const FORM_KEY = 'motion.form.v1';
const JOB_KEY = 'motion.job';
export const ACTIVE = ['queued', 'writing', 'voicing', 'rendering'];

function defaultVoice() {
  const lang = navigator.language || '';
  if (lang.startsWith('hi')) return 'hi-IN-MadhurNeural';
  if (lang.startsWith('zh')) return 'zh-CN-YunxiNeural';
  return 'en-US-AndrewNeural';
}

// Everything but the AI key is remembered between visits; the key stays in memory only.
function loadForm() {
  const base = { charMode: 'upload3d', character: null, provider: 'openai', model: 'gpt-5-mini', baseUrl: '',
    title: '', topic: '', description: '', voice: defaultVoice() };
  try {
    return { ...base, ...JSON.parse(localStorage.getItem(FORM_KEY) || '{}') };
  } catch {
    return base;
  }
}

export default function App() {
  const [options, setOptions] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [needsServerKey, setNeedsServerKey] = useState(false);
  const [form, setForm] = useState(loadForm);
  const [apiKey, setApiKey] = useState('');
  const [section, setSection] = useState('character');
  const [preview, setPreview] = useState({ kind: 'none', url: null });
  const [previewError, setPreviewError] = useState('');
  const [job, setJob] = useState(null);
  const [submitError, setSubmitError] = useState('');
  const [videoUrl, setVideoUrl] = useState(null);
  const restored = useRef(false);

  const update = (patch) => setForm((f) => ({ ...f, ...patch }));

  useEffect(() => {
    try { localStorage.setItem(FORM_KEY, JSON.stringify(form)); } catch { /* private mode: nothing to keep */ }
  }, [form]);

  async function loadOptions() {
    setLoadError(null);
    try {
      setOptions(await api.options());
      setNeedsServerKey(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setNeedsServerKey(true);
      else setLoadError(error.message);
    }
  }
  useEffect(() => { loadOptions(); }, []);

  // Restore the saved character's preview (and drop it if the file is gone), plus a job still in flight.
  useEffect(() => {
    if (!options || restored.current) return;
    restored.current = true;
    const ch = form.character;
    if (form.charMode !== 'none' && ch?.id) {
      api.characterUrl(ch.id)
        .then((url) => setPreview({ kind: ch.kind, url }))
        .catch(() => update({ character: null }));
    }
    const jobId = sessionStorage.getItem(JOB_KEY);
    if (jobId) api.job(jobId).then((j) => { setJob(j); setSection('output'); }).catch(() => sessionStorage.removeItem(JOB_KEY));
  }, [options]); // eslint-disable-line react-hooks/exhaustive-deps -- runs once, when options first arrive

  // Poll the running job; fetch the video once it is done.
  useEffect(() => {
    if (!job || !ACTIVE.includes(job.status)) return undefined;
    const timer = setTimeout(async () => {
      try { setJob(await api.job(job.id)); } catch (error) {
        if (error.status === 404) { sessionStorage.removeItem(JOB_KEY); setJob(null); }
        else setJob({ ...job }); // transient: poll again
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [job]);

  useEffect(() => {
    if (job?.status !== 'done' || videoUrl) return;
    api.videoUrl(job.id).then(setVideoUrl).catch((error) => setSubmitError(error.message));
  }, [job, videoUrl]);

  const provider = options?.providers.find((p) => p.id === form.provider);
  const done = {
    character: form.charMode === 'none' || Boolean(form.character?.id),
    writer: Boolean(provider && form.model.trim() && (!provider.needs_key || apiKey.trim())
      && (!provider.needs_base_url || form.baseUrl.trim())),
    video: Boolean(form.title.trim() && form.topic.trim() && form.voice),
  };
  const missing = [
    !done.character && ['character', 'Pick a character'],
    !done.writer && ['writer', provider?.needs_key && !apiKey.trim() ? 'Add your API key' : 'Finish the script writer'],
    !done.video && ['video', 'Add a title and topic'],
  ].filter(Boolean);
  const busy = Boolean(job && ACTIVE.includes(job.status));
  const finished = job?.status === 'done'; // a new video starts from "Make another video", never by overwriting this one
  const renderer = options?.renderer.installed !== false;
  const hint = finished ? 'Your Short is ready.' : busy ? 'A video is being made.' : missing[0]?.[1] ?? 'Ready when you are.';

  // Blob URLs hold whole files in memory: release each one when it is replaced or the page closes.
  useEffect(() => () => { if (preview.url) URL.revokeObjectURL(preview.url); }, [preview.url]);
  useEffect(() => () => { if (videoUrl) URL.revokeObjectURL(videoUrl); }, [videoUrl]);

  async function generate() {
    setSubmitError('');
    setVideoUrl(null);
    setSection('output');
    try {
      const { job_id: id } = await api.createJob({
        title: form.title, topic: form.topic, description: form.description, voice: form.voice,
        character_id: form.charMode === 'none' ? null : form.character?.id ?? null,
        llm: { provider: form.provider, model: form.model, api_key: apiKey || null, base_url: form.baseUrl || null },
      });
      sessionStorage.setItem(JOB_KEY, id);
      setJob({ id, title: form.title, status: 'queued', progress: 0, overall: 0, message: '', result: null });
    } catch (error) {
      setSubmitError(error.message);
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      setJob(await api.cancel(job.id));
    } catch (error) {
      setSubmitError(`Couldn't cancel: ${error.message}`); // the job is still running; keep polling it
    }
  }

  function startOver() {
    sessionStorage.removeItem(JOB_KEY);
    setJob(null);
    setVideoUrl(null);
    setSubmitError('');
    setSection('video');
  }

  const sections = {
    character: <Character form={form} update={update} options={options} setPreview={setPreview} onNext={() => setSection('writer')} />,
    writer: <Writer form={form} update={update} providers={options?.providers ?? []} apiKey={apiKey} setApiKey={setApiKey} onNext={() => setSection('video')} />,
    video: <Brief form={form} update={update} voices={options?.voices ?? []} missing={missing} busy={busy} finished={finished}
      onGenerate={generate} onGo={setSection} />,
    output: <Output job={job} videoUrl={videoUrl} error={submitError} missing={missing} busy={busy} renderer={renderer}
      onGenerate={generate} onCancel={cancel} onStartOver={startOver} onGo={setSection} />,
  };

  return (
    <div className="shell">
      <Rail section={section} onSelect={setSection} done={done} job={job} hint={hint}
        canGenerate={missing.length === 0 && !busy && !finished && Boolean(options) && renderer} onGenerate={generate} />
      <main className="main">
        {needsServerKey && <ServerKeyPrompt onSaved={loadOptions} />}
        {loadError && <Notice tone="error" title="Can't load the studio" action={<button type="button" className="btn btn-quiet" onClick={loadOptions}>Try again</button>}>{loadError}</Notice>}
        {options && !renderer && (
          <Notice tone="warn" title="The renderer isn't installed">
            Videos are drawn in a headless browser. Run <code>uv pip install playwright</code>, then restart <code>python main.py</code>.
          </Notice>
        )}
        <div className="panel" key={section}>{options ? sections[section] : !loadError && !needsServerKey && <PanelSkeleton />}</div>
      </main>
      <Phone character={form.charMode === 'none' ? { kind: 'none', url: null } : preview} title={form.title}
        job={job} videoUrl={videoUrl} error={previewError} setError={setPreviewError} />
    </div>
  );
}

function PanelSkeleton() {
  return (
    <div className="skeleton" aria-hidden="true">
      <span className="sk sk-title" /><span className="sk sk-line" /><span className="sk sk-block" /><span className="sk sk-block" />
    </div>
  );
}

function ServerKeyPrompt({ onSaved }) {
  const [value, setValue] = useState('');
  return (
    <Notice tone="warn" title="This server needs its access key">
      <form className="inline-form" onSubmit={(e) => { e.preventDefault(); serverKey.set(value.trim()); onSaved(); }}>
        <Field label="MoneyPrinterTurbo access key" hint="The app.api_key value from config.toml. Kept for this tab only.">
          {(id) => <input id={id} type="password" className="input" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />}
        </Field>
        <button type="submit" className="btn btn-primary" disabled={!value.trim()}>Unlock</button>
      </form>
    </Notice>
  );
}
