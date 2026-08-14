"use client";

import { useCallback, useEffect, useState } from "react";

type Task = {
  task_id: string;
  state: number;
  progress: number;
  video_subject?: string;
  videos?: string[] | null;
  error?: string | null;
};

type FormState = {
  subject: string;
  script: string;
  keywords: string;
  language: string;
  source: "pexels" | "pixabay" | "coverr";
  concat: "random" | "sequential";
  transition: "none" | "fade" | "slide";
  aspect: "portrait" | "landscape";
  clipDuration: number;
  clipSpeed: number;
  videoCount: number;
  voiceover: "auto" | "none";
  voice: string;
  voiceVolume: number;
  voiceRate: number;
  music: "random" | "none";
  musicVolume: number;
  subtitles: boolean;
  font: string;
  subtitlePosition: "top" | "center" | "bottom";
  fontSize: number;
  subtitleColor: string;
  outline: boolean;
};

const TASK_PROCESSING = 4;
const TASK_COMPLETE = 1;

const initialForm: FormState = {
  subject: "",
  script: "",
  keywords: "",
  language: "auto",
  source: "pexels",
  concat: "random",
  transition: "none",
  aspect: "portrait",
  clipDuration: 3,
  clipSpeed: 1,
  videoCount: 1,
  voiceover: "auto",
  voice: "zh-CN-XiaoxiaoNeural-Female",
  voiceVolume: 1,
  voiceRate: 1,
  music: "random",
  musicVolume: 0.2,
  subtitles: true,
  font: "BeVietnamPro-Bold.ttf",
  subtitlePosition: "bottom",
  fontSize: 30,
  subtitleColor: "#ffffff",
  outline: true,
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = (await response.json()) as { data?: T; message?: string };
  if (!response.ok) throw new Error(payload.message || "The request failed.");
  return payload.data as T;
}

function assetUrl(path: string) {
  return path.startsWith("http") ? path : `http://127.0.0.1:8080${path}`;
}

function taskLabel(task: Task | null) {
  if (!task) return "Ready to create";
  if (task.state === TASK_PROCESSING) return "Rendering video";
  if (task.state === TASK_COMPLETE) return "Video ready";
  return "Generation failed";
}

export default function Home() {
  const [form, setForm] = useState<FormState>(initialForm);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [currentTask, setCurrentTask] = useState<Task | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGeneratingScript, setIsGeneratingScript] = useState(false);
  const [error, setError] = useState("");

  const loadTasks = useCallback(async () => {
    try {
      const data = await api<{ tasks: Task[] }>("/tasks?page=1&page_size=8");
      setTasks(data.tasks ?? []);
    } catch {
      // The API may still be starting with webui-next.bat.
    }
  }, []);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    if (!currentTask || currentTask.state !== TASK_PROCESSING) return;
    const timer = window.setInterval(async () => {
      try {
        const task = await api<Task>(`/tasks/${currentTask.task_id}`);
        setCurrentTask(task);
        if (task.state !== TASK_PROCESSING) await loadTasks();
      } catch {
        // Keep the last known status visible during a brief reconnect.
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [currentTask, loadTasks]);

  const updateForm = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((previous) => ({ ...previous, [key]: value }));
  };

  const generateScript = async () => {
    if (!form.subject.trim()) {
      setError("Add a video subject first.");
      return;
    }
    setError("");
    setIsGeneratingScript(true);
    try {
      const data = await api<{ video_script: string }>("/scripts", {
        method: "POST",
        body: JSON.stringify({ video_subject: form.subject, video_language: form.language === "auto" ? "" : form.language }),
      });
      updateForm("script", data.video_script || "");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Script generation failed.");
    } finally {
      setIsGeneratingScript(false);
    }
  };

  const generateVideo = async () => {
    if (!form.subject.trim() && !form.script.trim()) {
      setError("Add a subject or script before generating.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      const data = await api<{ task_id: string }>("/videos", {
        method: "POST",
        body: JSON.stringify({
          video_subject: form.subject,
          video_script: form.script,
          video_terms: form.keywords,
          video_language: form.language === "auto" ? "" : form.language,
          video_source: form.source,
          video_concat_mode: form.concat,
          video_transition_mode: form.transition === "none" ? null : form.transition,
          video_aspect: form.aspect,
          video_clip_duration: form.clipDuration,
          video_clip_speed: form.clipSpeed,
          video_count: form.videoCount,
          voice_name: form.voiceover === "none" ? "" : form.voice,
          voice_volume: form.voiceVolume,
          voice_rate: form.voiceRate,
          bgm_type: form.music,
          bgm_volume: form.musicVolume,
          subtitle_enabled: form.subtitles,
          subtitle_position: form.subtitlePosition,
          font_name: form.font,
          font_size: form.fontSize,
          text_fore_color: form.subtitleColor,
          stroke_color: form.outline ? "#000000" : "#00000000",
          stroke_width: form.outline ? 1.5 : 0,
        }),
      });
      setCurrentTask({ task_id: data.task_id, state: TASK_PROCESSING, progress: 0 });
      await loadTasks();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Video generation failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const previewVideo = currentTask?.videos?.[0];
  const progress = currentTask?.progress ?? 0;

  return (
    <main className="studio-shell flex min-h-screen flex-col overflow-auto px-3 py-3 sm:px-5 lg:h-screen lg:min-h-[620px] lg:overflow-hidden lg:px-7">
      <header className="glass mb-3 flex shrink-0 items-center justify-between rounded-2xl px-4 py-2.5 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#ff5b62] to-[#8f73ff] text-lg font-black shadow-lg shadow-[#ff5b62]/20">✦</div>
          <div className="min-w-0"><div className="flex items-baseline gap-2"><h1 className="truncate text-lg font-bold tracking-[-0.045em] sm:text-xl">MoneyPrinterTurbo</h1><span className="text-[11px] font-semibold text-[#77798b]">v1.3.4</span></div><p className="hidden text-[11px] text-[#77798b] sm:block">Short-form video studio</p></div>
        </div>
        <div className="flex items-center gap-2 text-xs sm:text-sm"><span className="hidden items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/[0.07] px-3 py-2 text-emerald-200 sm:flex"><span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_10px_#34d399]" />Local workspace</span><button className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 font-semibold text-white transition hover:bg-white/[0.08]" onClick={loadTasks}>Tasks <span className="ml-1 text-[#9899aa]">{tasks.length}</span></button></div>
      </header>

      <section className="min-h-0 flex-1">
        <div className="studio-panels grid h-full min-h-0 gap-3 lg:grid-cols-4">
          <Panel title="Video Script" eyebrow="01" accent>
            <Field label="Video subject"><textarea className="compact-textarea h-16" placeholder="How AI is changing everyday life" value={form.subject} onChange={(event) => updateForm("subject", event.target.value)} /></Field>
            <Field label="Script language"><select className="compact-input" value={form.language} onChange={(event) => updateForm("language", event.target.value)}><option value="auto">Auto Detect</option><option value="en-US">English</option><option value="zh-CN">中文</option><option value="es-ES">Español</option><option value="hi-IN">हिन्दी</option></select></Field>
            <div className="compact-expander"><span>⌄</span> Advanced script settings</div>
            <MiniButton onClick={generateScript} disabled={isGeneratingScript}>{isGeneratingScript ? "Writing script..." : "✦ Generate script & keywords"}</MiniButton>
            <Field label="Video script"><textarea className="compact-textarea h-32" placeholder="Write or generate the narration..." value={form.script} onChange={(event) => updateForm("script", event.target.value)} /></Field>
            <MiniButton onClick={generateScript} disabled={isGeneratingScript}>{isGeneratingScript ? "Working..." : "✦ Generate keywords with AI"}</MiniButton>
            <Field label="Video keywords"><input className="compact-input" placeholder="technology, people, future" value={form.keywords} onChange={(event) => updateForm("keywords", event.target.value)} /></Field>
          </Panel>

          <Panel title="Video Settings" eyebrow="02">
            <Field label="Video source"><select className="compact-input" value={form.source} onChange={(event) => updateForm("source", event.target.value as FormState["source"])}><option value="pexels">Pexels</option><option value="pixabay">Pixabay</option><option value="coverr">Coverr</option></select></Field>
            <Field label="Concatenation"><select className="compact-input" value={form.concat} onChange={(event) => updateForm("concat", event.target.value as FormState["concat"])}><option value="random">Random (Recommended)</option><option value="sequential">Sequential</option></select></Field>
            <Check label="Match visuals to script order" checked={form.concat === "sequential"} onChange={(checked) => updateForm("concat", checked ? "sequential" : "random")} />
            <Field label="Transition"><select className="compact-input" value={form.transition} onChange={(event) => updateForm("transition", event.target.value as FormState["transition"])}><option value="none">None</option><option value="fade">Fade</option><option value="slide">Slide</option></select></Field>
            <Field label="Aspect ratio"><div className="grid grid-cols-2 gap-2"><Choice active={form.aspect === "portrait"} onClick={() => updateForm("aspect", "portrait")}>Portrait 9:16</Choice><Choice active={form.aspect === "landscape"} onClick={() => updateForm("aspect", "landscape")}>Landscape 16:9</Choice></div></Field>
            <Field label={`Maximum clip duration · ${form.clipDuration}s`}><input className="compact-range" type="range" min="2" max="15" value={form.clipDuration} onChange={(event) => updateForm("clipDuration", Number(event.target.value))} /></Field>
            <Field label={`Clip speed · ${form.clipSpeed.toFixed(2)}×`}><input className="compact-range" type="range" min="0.5" max="2" step="0.05" value={form.clipSpeed} onChange={(event) => updateForm("clipSpeed", Number(event.target.value))} /></Field>
            <Field label="Videos per run"><select className="compact-input" value={form.videoCount} onChange={(event) => updateForm("videoCount", Number(event.target.value))}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option></select></Field>
          </Panel>

          <Panel title="Audio Settings" eyebrow="03">
            <Field label="Voiceover mode"><div className="grid grid-cols-2 gap-1 rounded-lg border border-white/10 bg-black/10 p-1"><Choice active={form.voiceover === "auto"} onClick={() => updateForm("voiceover", "auto")}>Auto</Choice><Choice active={form.voiceover === "none"} onClick={() => updateForm("voiceover", "none")}>None</Choice></div></Field>
            <Field label="Voice service"><select className="compact-input"><option>Azure TTS v1</option><option>Edge TTS</option><option>Chatterbox</option></select></Field>
            <Field label="Voice"><select className="compact-input" value={form.voice} onChange={(event) => updateForm("voice", event.target.value)}><option value="zh-CN-XiaoxiaoNeural-Female">Xiaoxiao · Female</option><option value="en-US-JennyNeural-Female">Jenny · Female</option><option value="en-US-GuyNeural-Male">Guy · Male</option></select></Field>
            <div className="grid grid-cols-2 gap-2"><Field label={`Volume · ${Math.round(form.voiceVolume * 100)}%`}><input className="compact-range" type="range" min="0" max="2" step="0.1" value={form.voiceVolume} onChange={(event) => updateForm("voiceVolume", Number(event.target.value))} /></Field><Field label={`Speed · ${form.voiceRate.toFixed(1)}×`}><input className="compact-range" type="range" min="0.5" max="2" step="0.1" value={form.voiceRate} onChange={(event) => updateForm("voiceRate", Number(event.target.value))} /></Field></div>
            <div className="my-1 border-t border-white/10" />
            <Field label="Background music"><select className="compact-input" value={form.music} onChange={(event) => updateForm("music", event.target.value as FormState["music"])}><option value="random">Random background music</option><option value="none">No music</option></select></Field>
            <Field label={`Music volume · ${Math.round(form.musicVolume * 100)}%`}><input className="compact-range" type="range" min="0" max="1" step="0.05" value={form.musicVolume} onChange={(event) => updateForm("musicVolume", Number(event.target.value))} /></Field>
            <div className="compact-note">Voiceover and music stay balanced automatically during rendering.</div>
          </Panel>

          <Panel title="Subtitle Settings" eyebrow="04">
            <Check label="Enable subtitles" checked={form.subtitles} onChange={(checked) => updateForm("subtitles", checked)} strong />
            <Field label="Font"><select className="compact-input" value={form.font} onChange={(event) => updateForm("font", event.target.value)}><option>BeVietnamPro-Bold.ttf</option><option>MicrosoftYaHeiBold.ttc</option><option>STHeitiMedium.ttc</option></select></Field>
            <Field label="Position"><select className="compact-input" value={form.subtitlePosition} onChange={(event) => updateForm("subtitlePosition", event.target.value as FormState["subtitlePosition"])}><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></select></Field>
            <div className="grid grid-cols-2 gap-2"><Field label="Color"><input className="h-9 w-full cursor-pointer rounded-lg border border-white/10 bg-[#10111a] p-1" type="color" value={form.subtitleColor} onChange={(event) => updateForm("subtitleColor", event.target.value)} /></Field><Field label={`Font size · ${form.fontSize}`}><input className="compact-range mt-3" type="range" min="18" max="80" value={form.fontSize} onChange={(event) => updateForm("fontSize", Number(event.target.value))} /></Field></div>
            <Check label="Outline" checked={form.outline} onChange={(checked) => updateForm("outline", checked)} />
            <div className="rounded-xl border border-white/10 bg-[#10111a] p-4 text-center" style={{ color: form.subtitleColor, fontSize: `${Math.min(form.fontSize, 38)}px`, textShadow: form.outline ? "1px 1px 0 #000, -1px -1px 0 #000" : "none" }}>Your captions look like this</div>
            <button className="compact-button mt-auto" onClick={() => setForm((previous) => ({ ...previous, subtitles: true, font: initialForm.font, subtitlePosition: "bottom", fontSize: 30, subtitleColor: "#ffffff", outline: true }))}>↻ Restore subtitle defaults</button>
          </Panel>
        </div>
      </section>

      {error && <div className="mt-2 shrink-0 rounded-xl border border-rose-400/25 bg-rose-400/[0.08] px-3 py-2 text-xs text-rose-100">{error}</div>}
      <footer className="glass mt-3 flex shrink-0 flex-wrap items-center gap-3 rounded-2xl px-4 py-2.5 sm:px-5">
        <div className="min-w-[180px] flex-1"><div className="flex items-center justify-between text-xs"><span className="font-semibold text-white">{taskLabel(currentTask)}</span><span className="text-[#ff8f94]">{currentTask ? `${progress}%` : "—"}</span></div><div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.08]"><div className="h-full rounded-full bg-gradient-to-r from-[#ff5b62] to-[#a57eff] transition-all duration-500" style={{ width: `${progress}%` }} /></div></div>
        {previewVideo && <a className="rounded-lg border border-emerald-400/25 bg-emerald-400/[0.08] px-3 py-2 text-xs font-semibold text-emerald-100" href={assetUrl(previewVideo)} download>Download result ↓</a>}
        <button className="rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-[#b2b3c1] transition hover:bg-white/[0.05]" onClick={() => setForm(initialForm)}>Reset</button>
        <button className="rounded-lg bg-gradient-to-r from-[#ff5b62] to-[#f07679] px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-[#ff5b62]/20 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60" onClick={generateVideo} disabled={isSubmitting}>{isSubmitting ? "Starting..." : "Generate video  ↗"}</button>
      </footer>
    </main>
  );
}

function Panel({ title, eyebrow, accent, children }: { title: string; eyebrow: string; accent?: boolean; children: React.ReactNode }) {
  return <section className={`studio-panel glass flex min-h-0 flex-col rounded-2xl p-3.5 ${accent ? "studio-panel-accent" : ""}`}><div className="mb-3 flex shrink-0 items-center justify-between border-b border-white/10 pb-2.5"><div className="flex items-center gap-2"><span className="grid h-5 w-5 place-items-center rounded-md bg-white/[0.07] text-[9px] font-bold text-[#9899aa]">{eyebrow}</span><h2 className="text-sm font-bold tracking-[-0.02em] text-white">{title}</h2></div><span className="h-1.5 w-1.5 rounded-full bg-[#ff5b62] opacity-70" /></div><div className="studio-panel-content min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">{children}</div></section>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-[#d6d6df]">{label}</span>{children}</label>;
}

function MiniButton({ onClick, disabled, children }: { onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return <button className="compact-button w-full" onClick={onClick} disabled={disabled}>{children}</button>;
}

function Choice({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button className={`rounded-md px-2 py-2 text-[11px] font-semibold transition ${active ? "bg-[#ff5b62]/15 text-[#ff9b9f] shadow-[inset_0_0_0_1px_rgba(255,91,98,.35)]" : "text-[#9899aa] hover:bg-white/[0.06] hover:text-white"}`} onClick={onClick}>{children}</button>;
}

function Check({ label, checked, onChange, strong }: { label: string; checked: boolean; onChange: (value: boolean) => void; strong?: boolean }) {
  return <button className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[11px] transition hover:bg-white/[0.04] ${strong ? "font-semibold text-white" : "text-[#b8b8c5]"}`} onClick={() => onChange(!checked)}><span className={`grid h-4 w-4 place-items-center rounded border text-[10px] ${checked ? "border-[#ff5b62] bg-[#ff5b62] text-white" : "border-white/20 bg-white/[0.03] text-transparent"}`}>✓</span>{label}</button>;
}
