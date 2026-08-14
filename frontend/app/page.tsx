"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type Step = "story" | "visuals" | "sound" | "captions";

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
  source: "pexels" | "pixabay" | "coverr";
  aspect: "portrait" | "landscape";
  clipDuration: number;
  voiceover: "auto" | "none";
  voiceVolume: number;
  subtitles: boolean;
  subtitlePosition: "top" | "center" | "bottom";
};

const TASK_PROCESSING = 4;
const TASK_COMPLETE = 1;

const steps: Array<{ id: Step; label: string; hint: string }> = [
  { id: "story", label: "Story", hint: "Shape the idea" },
  { id: "visuals", label: "Visuals", hint: "Choose the look" },
  { id: "sound", label: "Sound", hint: "Set the voice" },
  { id: "captions", label: "Captions", hint: "Polish the frame" },
];

const initialForm: FormState = {
  subject: "",
  script: "",
  keywords: "",
  source: "pexels",
  aspect: "portrait",
  clipDuration: 5,
  voiceover: "auto",
  voiceVolume: 1,
  subtitles: true,
  subtitlePosition: "bottom",
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

function stateLabel(task: Task) {
  if (task.state === TASK_COMPLETE) return "Ready to watch";
  if (task.state === TASK_PROCESSING) return "Rendering your video";
  return "Needs attention";
}

export default function Home() {
  const [activeStep, setActiveStep] = useState<Step>("story");
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
      // The UI remains usable while the API is being started by the batch file.
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
        if (task.state !== TASK_PROCESSING) {
          await loadTasks();
        }
      } catch {
        // Keep the last known status visible if the backend briefly reconnects.
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [currentTask, loadTasks]);

  const updateForm = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((previous) => ({ ...previous, [key]: value }));
  };

  const generateScript = async () => {
    if (!form.subject.trim()) {
      setError("Add a video idea first.");
      setActiveStep("story");
      return;
    }
    setError("");
    setIsGeneratingScript(true);
    try {
      const data = await api<{ video_script: string }>("/scripts", {
        method: "POST",
        body: JSON.stringify({ video_subject: form.subject, video_language: "" }),
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
      setError("Give your video a subject or script before generating.");
      setActiveStep("story");
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
          video_source: form.source,
          video_aspect: form.aspect,
          video_clip_duration: form.clipDuration,
          voice_name: form.voiceover === "none" ? "" : "zh-CN-XiaoxiaoNeural-Female",
          voice_volume: form.voiceVolume,
          subtitle_enabled: form.subtitles,
          subtitle_position: form.subtitlePosition,
          video_count: 1,
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

  const previewTitle = form.subject || "Your next story starts here";
  const previewVideo = currentTask?.videos?.[0];
  const progress = currentTask?.progress ?? 0;

  const stepContent = useMemo(() => {
    switch (activeStep) {
      case "visuals":
        return (
          <div className="grid gap-7 md:grid-cols-[1.2fr_0.8fr]">
            <FieldGroup label="Video source" description="Pick the library used to find your clips.">
              <div className="grid grid-cols-3 gap-2">
                {(["pexels", "pixabay", "coverr"] as const).map((source) => (
                  <ChoiceButton key={source} active={form.source === source} onClick={() => updateForm("source", source)}>
                    {source[0].toUpperCase() + source.slice(1)}
                  </ChoiceButton>
                ))}
              </div>
            </FieldGroup>
            <FieldGroup label="Frame" description="Choose the format for your destination.">
              <div className="grid grid-cols-2 gap-2">
                <ChoiceButton active={form.aspect === "portrait"} onClick={() => updateForm("aspect", "portrait")}>
                  <span className="mr-2 inline-block h-5 w-3 rounded-sm border border-current" />9:16
                </ChoiceButton>
                <ChoiceButton active={form.aspect === "landscape"} onClick={() => updateForm("aspect", "landscape")}>
                  <span className="mr-2 inline-block h-3 w-5 rounded-sm border border-current" />16:9
                </ChoiceButton>
              </div>
            </FieldGroup>
            <FieldGroup label="Clip duration" description={`${form.clipDuration} seconds maximum per clip.`}>
              <input className="accent-[#ff5b62] w-full" type="range" min="2" max="15" value={form.clipDuration} onChange={(event) => updateForm("clipDuration", Number(event.target.value))} />
            </FieldGroup>
          </div>
        );
      case "sound":
        return (
          <div className="grid gap-7 md:grid-cols-[1.1fr_0.9fr]">
            <FieldGroup label="Voiceover" description="Let the pipeline narrate your script or keep it silent.">
              <div className="grid grid-cols-2 gap-2">
                <ChoiceButton active={form.voiceover === "auto"} onClick={() => updateForm("voiceover", "auto")}>Automatic voice</ChoiceButton>
                <ChoiceButton active={form.voiceover === "none"} onClick={() => updateForm("voiceover", "none")}>No voiceover</ChoiceButton>
              </div>
            </FieldGroup>
            <FieldGroup label="Voice volume" description={`${Math.round(form.voiceVolume * 100)}%`}>
              <input className="accent-[#ff5b62] w-full" type="range" min="0" max="2" step="0.1" value={form.voiceVolume} onChange={(event) => updateForm("voiceVolume", Number(event.target.value))} />
            </FieldGroup>
            <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.025] p-5 text-sm text-[#9899aa]">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-[#ff8f94]">Sound design</span>
              Background music and provider-specific voice controls will move here next, without adding another tall page section.
            </div>
          </div>
        );
      case "captions":
        return (
          <div className="grid gap-7 md:grid-cols-[1.1fr_0.9fr]">
            <FieldGroup label="Captions" description="Keep the story readable in the feed.">
              <button className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left text-sm transition ${form.subtitles ? "border-[#ff5b62]/50 bg-[#ff5b62]/10" : "border-white/10 bg-white/[0.03]"}`} onClick={() => updateForm("subtitles", !form.subtitles)}>
                <span>{form.subtitles ? "Captions enabled" : "Captions disabled"}</span>
                <span className={`h-5 w-9 rounded-full p-1 transition ${form.subtitles ? "bg-[#ff5b62]" : "bg-white/15"}`}><span className={`block h-3 w-3 rounded-full bg-white transition ${form.subtitles ? "translate-x-4" : ""}`} /></span>
              </button>
            </FieldGroup>
            <FieldGroup label="Position" description="Set the default caption anchor.">
              <div className="grid grid-cols-3 gap-2">
                {(["top", "center", "bottom"] as const).map((position) => (
                  <ChoiceButton key={position} active={form.subtitlePosition === position} onClick={() => updateForm("subtitlePosition", position)}>{position}</ChoiceButton>
                ))}
              </div>
            </FieldGroup>
          </div>
        );
      default:
        return (
          <div className="grid gap-4 md:grid-cols-2">
            <FieldGroup label="Video idea" description="One clear sentence to anchor the story.">
              <textarea className="min-h-28 w-full resize-y rounded-xl border border-white/10 bg-[#10111a] px-3.5 py-3 text-sm text-white outline-none transition placeholder:text-[#646678] focus:border-[#ff5b62]/60 focus:ring-4 focus:ring-[#ff5b62]/10" placeholder="Example: How AI is changing everyday life" value={form.subject} onChange={(event) => updateForm("subject", event.target.value)} />
            </FieldGroup>
            <FieldGroup label="Video script" description="Optional — write it or generate it with AI.">
              <textarea className="min-h-28 w-full resize-y rounded-xl border border-white/10 bg-[#10111a] px-3.5 py-3 text-sm leading-5 text-white outline-none transition placeholder:text-[#646678] focus:border-[#ff5b62]/60 focus:ring-4 focus:ring-[#ff5b62]/10" placeholder="Your narration will appear here..." value={form.script} onChange={(event) => updateForm("script", event.target.value)} />
              <button className="mt-2 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-white transition hover:border-[#ff5b62]/50 hover:bg-[#ff5b62]/10 disabled:cursor-wait disabled:opacity-50" onClick={generateScript} disabled={isGeneratingScript}>{isGeneratingScript ? "Writing..." : "Generate with AI"}</button>
            </FieldGroup>
            <div className="md:col-span-2">
              <FieldGroup label="Keywords" description="Optional — comma-separated visual hints.">
                <input className="w-full rounded-xl border border-white/10 bg-[#10111a] px-3.5 py-3 text-sm text-white outline-none transition placeholder:text-[#646678] focus:border-[#ff5b62]/60 focus:ring-4 focus:ring-[#ff5b62]/10" placeholder="technology, people, future, creativity" value={form.keywords} onChange={(event) => updateForm("keywords", event.target.value)} />
              </FieldGroup>
            </div>
          </div>
        );
    }
  }, [activeStep, form, isGeneratingScript]);

  return (
    <main className="mx-auto min-h-screen max-w-[1480px] px-4 pb-5 pt-3 sm:px-6 lg:px-8">
      <header className="glass subtle-ring mb-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl px-4 py-2.5 sm:px-5">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-[#ff5b62] to-[#8f73ff] text-lg font-black shadow-lg shadow-[#ff5b62]/20">✦</div>
          <div>
            <div className="flex items-baseline gap-2"><h1 className="text-lg font-bold tracking-[-0.04em] sm:text-xl">MoneyPrinterTurbo</h1><span className="text-[11px] font-semibold text-[#77798b]">v1.3.4</span></div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="hidden items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/[0.07] px-3 py-2 text-emerald-200 sm:flex"><span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_10px_#34d399]" />Local workspace</span>
          <button className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2.5 font-semibold text-white transition hover:border-white/20 hover:bg-white/[0.08]" onClick={loadTasks}>Task manager <span className="ml-1 text-[#9899aa]">{tasks.length}</span></button>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="glass rounded-2xl p-4 sm:p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div><p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#ff8f94]">Creation workspace</p><h2 className="mt-1 text-xl font-bold tracking-[-0.04em] sm:text-2xl">Build your next video</h2></div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] px-2.5 py-1.5 text-right text-xs"><span className="text-[#77798b]">Step </span><span className="font-semibold">{steps.findIndex((step) => step.id === activeStep) + 1}<span className="text-[#77798b]"> / {steps.length}</span></span></div>
          </div>

          <nav className="mb-4 grid grid-cols-4 gap-1 rounded-xl border border-white/10 bg-black/10 p-1">
            {steps.map((step, index) => <button key={step.id} className={`rounded-lg px-2 py-2 text-center transition ${activeStep === step.id ? "bg-[#ff5b62]/12 text-white shadow-[inset_0_0_0_1px_rgba(255,91,98,.32)]" : "text-[#77798b] hover:bg-white/[0.04] hover:text-white"}`} onClick={() => setActiveStep(step.id)}><span className="mr-1 inline-grid h-5 w-5 place-items-center rounded-md bg-white/[0.06] text-[10px] font-bold">{index + 1}</span><span className="text-xs font-semibold sm:text-sm">{step.label}</span></button>)}
          </nav>

          <div className="min-h-[290px]">{stepContent}</div>
          {error && <div className="mt-5 rounded-xl border border-rose-400/25 bg-rose-400/[0.08] px-4 py-3 text-sm text-rose-100">{error}</div>}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-3"><p className="text-[11px] text-[#77798b]">Change any step before rendering.</p><div className="flex gap-2"><button className="rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-[#b2b3c1] transition hover:bg-white/[0.05]" onClick={() => setForm(initialForm)}>Reset</button><button className="rounded-lg bg-gradient-to-r from-[#ff5b62] to-[#f07679] px-4 py-2 text-xs font-bold text-white shadow-lg shadow-[#ff5b62]/20 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60" onClick={generateVideo} disabled={isSubmitting}>{isSubmitting ? "Starting..." : "Generate video  ↗"}</button></div></div>
        </section>

        <aside className="space-y-5">
          <section className="glass overflow-hidden rounded-2xl p-3">
            <div className="mb-3 flex items-center justify-between px-1"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#77798b]">Preview</p><h3 className="mt-1 font-semibold">Your final frame</h3></div><span className="rounded-full border border-white/10 px-2.5 py-1 text-[11px] text-[#9899aa]">{form.aspect === "portrait" ? "9:16" : "16:9"}</span></div>
            <div className={`phone-grid relative mx-auto flex h-52 max-w-[180px] items-end overflow-hidden rounded-[1.5rem] border border-white/10 bg-gradient-to-b from-[#28294a] via-[#17182b] to-[#10111a] p-4 ${form.aspect === "landscape" ? "h-36 max-w-none" : ""}`}>
              {previewVideo ? <video className="absolute inset-0 h-full w-full object-cover" src={assetUrl(previewVideo)} controls /> : <><div className="absolute left-1/2 top-1/3 h-24 w-24 -translate-x-1/2 rounded-full bg-[#ff5b62]/20 blur-2xl" /><div className="relative z-10"><div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#ff8f94]">MoneyPrinterTurbo</div><p className="max-w-[180px] text-xl font-bold leading-tight tracking-[-0.04em]">{previewTitle}</p><div className="mt-4 h-1 w-16 rounded-full bg-[#ff5b62]" /></div></>}
            </div>
          </section>

          <section className="glass rounded-2xl p-4">
            <div className="mb-4 flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#77798b]">Live status</p><h3 className="mt-1 font-semibold">{currentTask ? stateLabel(currentTask) : "Ready when you are"}</h3></div><span className="text-sm font-bold text-[#ff8f94]">{currentTask ? `${progress}%` : "—"}</span></div>
            <div className="h-2 overflow-hidden rounded-full bg-white/[0.08]"><div className="h-full rounded-full bg-gradient-to-r from-[#ff5b62] to-[#a57eff] transition-all duration-500" style={{ width: `${progress}%` }} /></div>
            <p className="mt-3 text-xs leading-5 text-[#77798b]">{currentTask?.error || (currentTask?.state === TASK_COMPLETE ? "Your video is ready to preview and download." : "Generation progress will stay here while you continue planning the next one.")}</p>
            {previewVideo && <a className="mt-4 block rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-center text-sm font-semibold text-white transition hover:bg-white/[0.08]" href={assetUrl(previewVideo)} download>Download video ↓</a>}
          </section>

          <section className="glass rounded-2xl p-4"><div className="mb-3 flex items-center justify-between"><div><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#77798b]">Recent work</p><h3 className="mt-1 text-sm font-semibold">Task history</h3></div><span className="rounded-full bg-white/[0.06] px-2 py-1 text-xs text-[#9899aa]">{tasks.length}</span></div><div className="space-y-1.5">{tasks.length === 0 ? <p className="rounded-lg border border-dashed border-white/10 px-3 py-3 text-[11px] leading-4 text-[#77798b]">Your generated videos will appear here.</p> : tasks.slice(0, 4).map((task) => <button key={task.task_id} className="w-full rounded-lg border border-white/10 bg-white/[0.025] p-2.5 text-left transition hover:border-white/20 hover:bg-white/[0.06]" onClick={() => setCurrentTask(task)}><div className="flex items-center justify-between gap-3"><span className="truncate text-xs font-medium">{task.video_subject || "Untitled video"}</span><span className="text-[11px] text-[#ff8f94]">{task.progress}%</span></div><div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/[0.08]"><div className="h-full rounded-full bg-[#ff5b62]" style={{ width: `${task.progress}%` }} /></div></button>)}</div></section>
        </aside>
      </div>
    </main>
  );
}

function FieldGroup({ label, description, children }: { label: string; description: string; children: React.ReactNode }) {
  return <div><div className="mb-3 flex items-end justify-between gap-3"><div><label className="text-sm font-semibold text-white">{label}</label><p className="mt-1 text-xs text-[#77798b]">{description}</p></div></div>{children}</div>;
}

function ChoiceButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button className={`rounded-xl border px-3 py-3 text-sm font-semibold transition ${active ? "border-[#ff5b62]/55 bg-[#ff5b62]/12 text-white" : "border-white/10 bg-white/[0.03] text-[#9899aa] hover:border-white/20 hover:text-white"}`} onClick={onClick}>{children}</button>;
}
