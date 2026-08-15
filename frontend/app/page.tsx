"use client";

import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  FileAudio,
  FileVideo,
  FolderOpen,
  History,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Mic2,
  Play,
  RefreshCw,
  RotateCcw,
  Settings,
  Sparkles,
  Trash2,
  Upload,
  WandSparkles,
  X,
} from "lucide-react";
import { ChangeEvent, ReactNode, useEffect, useMemo, useState } from "react";

const BACKEND_ORIGIN = "http://127.0.0.1:8080";
const PROCESSING = 4;
const COMPLETE = 1;
const FAILED = -1;

type VoiceMode = "tts" | "upload" | "none";
type SettingsMap = Record<string, Record<string, unknown>>;

type Material = { name: string; url: string };
type TaskEvent = {
  id?: string;
  timestamp?: number;
  message?: string;
  stage?: string;
  level?: string;
  progress?: number;
};
type Task = {
  task_id: string;
  state?: number;
  progress?: number;
  videos?: string[];
  combined_videos?: string[];
  error?: string;
  failed_stage?: string;
  params?: { video_subject?: string };
  video_subject?: string;
  warnings?: Array<{ code?: string; video_index?: number } | string>;
  events?: TaskEvent[];
  current_stage?: string;
  stage_label?: string;
};

type UiOptions = {
  version?: string;
  languages?: string[];
  defaults?: Record<string, string | number | boolean>;
  llm_providers?: Array<{ id: string; label: string; default_model: string; default_base_url: string; show_api_key: boolean; show_base_url: boolean; extra_fields: string[] }>;
  fonts: string[];
  songs: string[];
  voices: Record<string, string[]>;
  local_material_extensions: string[];
  audio_extensions: string[];
};

type FormState = {
  subject: string;
  language: string;
  paragraphNumber: number;
  scriptPrompt: string;
  systemPrompt: string;
  script: string;
  terms: string;
  source: "pexels" | "pixabay" | "coverr" | "local";
  concat: "random" | "sequential";
  matchOrder: boolean;
  transition: string;
  aspect: "9:16" | "16:9" | "1:1";
  clipDuration: number;
  clipSpeed: number;
  videoCount: number;
  videoCodec: string;
  voiceMode: VoiceMode;
  ttsServer: string;
  voice: string;
  voiceVolume: number;
  voiceRate: number;
  bgmType: string;
  bgmFile: string;
  bgmVolume: number;
  musicPrompt: string;
  subtitles: boolean;
  font: string;
  position: "top" | "center" | "bottom" | "custom";
  customPosition: number;
  fontColor: string;
  fontSize: number;
  strokeColor: string;
  strokeWidth: number;
  subtitleBackground: boolean;
  subtitleBackgroundColor: string;
  roundedBackground: boolean;
};

const initialForm: FormState = {
  subject: "",
  language: "",
  paragraphNumber: 1,
  scriptPrompt: "",
  systemPrompt: "",
  script: "",
  terms: "",
  source: "pexels",
  concat: "random",
  matchOrder: false,
  transition: "",
  aspect: "9:16",
  clipDuration: 3,
  clipSpeed: 1,
  videoCount: 1,
  videoCodec: "__default__",
  voiceMode: "tts",
  ttsServer: "azure-tts-v1",
  voice: "zh-CN-XiaoxiaoNeural-Female",
  voiceVolume: 1,
  voiceRate: 1,
  bgmType: "random",
  bgmFile: "",
  bgmVolume: 0.2,
  musicPrompt: "",
  subtitles: true,
  font: "",
  position: "bottom",
  customPosition: 70,
  fontColor: "#FFFFFF",
  fontSize: 60,
  strokeColor: "#000000",
  strokeWidth: 1.5,
  subtitleBackground: false,
  subtitleBackgroundColor: "#000000",
  roundedBackground: false,
};

const providers = [
  ["azure-tts-v1", "Azure TTS V1"],
  ["azure-tts-v2", "Azure TTS V2"],
  ["siliconflow", "SiliconFlow TTS"],
  ["gemini-tts", "Google Gemini TTS"],
  ["mimo-tts", "Xiaomi MiMo TTS"],
  ["minimax-tts", "MiniMax TTS"],
  ["elevenlabs", "ElevenLabs TTS"],
  ["chatterbox", "Chatterbox TTS"],
] as const;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.status >= 400) {
    throw new Error(body.message || `Request failed (${response.status})`);
  }
  return (body.data ?? body) as T;
}

function assetUrl(value: string) {
  if (!value) return "";
  return value.startsWith("http") ? value : `${BACKEND_ORIGIN}${value.startsWith("/") ? "" : "/"}${value}`;
}

function taskTitle(task: Task) {
  return task.params?.video_subject || task.video_subject || "Untitled video";
}

function taskStatus(task?: Task | null) {
  if (!task) return "Ready to create";
  if (task.state === PROCESSING) return "Generating video";
  if (task.state === COMPLETE) return "Video ready";
  if (task.state === FAILED) return "Generation failed";
  return "Task history";
}

function formatBytes(bytes: number) {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Home() {
  const [form, setForm] = useState<FormState>(initialForm);
  const [options, setOptions] = useState<UiOptions>({ fonts: ["MicrosoftYaHeiBold.ttc"], songs: [], voices: { "azure-tts-v1": ["zh-CN-XiaoxiaoNeural-Female"] }, local_material_extensions: [], audio_extensions: [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"] });
  const [materials, setMaterials] = useState<Material[]>([]);
  const [audioPath, setAudioPath] = useState("");
  const [audioPreviewUrl, setAudioPreviewUrl] = useState("");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [currentTask, setCurrentTask] = useState<Task | null>(null);
  const [taskId, setTaskId] = useState("");
  const [isGeneratingScript, setIsGeneratingScript] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [drawer, setDrawer] = useState<"tasks" | "settings" | null>(null);
  const [generationOpen, setGenerationOpen] = useState(false);
  const [generationMinimized, setGenerationMinimized] = useState(false);
  const [uiLanguage, setUiLanguage] = useState("en-US");
  const [settings, setSettings] = useState<SettingsMap>({});
  const [settingsDraft, setSettingsDraft] = useState({
    llmProvider: "openai",
    llmApiKey: "",
    llmBaseUrl: "",
    llmModel: "",
    pexels: "",
    pixabay: "",
    coverr: "",
    azureKey: "",
    azureRegion: "",
    geminiKey: "",
    minimaxKey: "",
  });

  const voices = options.voices[form.ttsServer] || [];
  const progress = currentTask?.progress || 0;
  const currentVideo = currentTask?.videos?.[0] || "";

  const setValue = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((previous) => ({ ...previous, [key]: value }));
  };

  const loadTasks = async () => {
    try {
      const result = await api<{ tasks: Task[] }>("/tasks?page=1&page_size=20");
      setTasks(result.tasks || []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load tasks");
    }
  };

  useEffect(() => {
    void Promise.all([
      api<UiOptions>("/ui/options").then((data) => {
        setOptions(data);
        const defaults = data.defaults || {};
        setUiLanguage(String(defaults.language || "en-US"));
        const defaultServer = String(defaults.tts_server || "azure-tts-v1");
        const serverVoices = data.voices[defaultServer] || data.voices["azure-tts-v1"] || [];
        setForm((previous) => ({
          ...previous,
          source: (defaults.video_source as FormState["source"]) || previous.source,
          videoCodec: String(defaults.video_codec || previous.videoCodec),
          ttsServer: defaultServer,
          voiceMode: (defaults.voice_mode as VoiceMode) || previous.voiceMode,
          voice: String(defaults.voice_name || serverVoices[0] || previous.voice),
          font: String(defaults.font_name || data.fonts[0] || previous.font),
          position: (defaults.subtitle_position as FormState["position"]) || previous.position,
          customPosition: Number(defaults.custom_position ?? previous.customPosition),
          fontColor: String(defaults.text_fore_color || previous.fontColor),
          fontSize: Number(defaults.font_size ?? previous.fontSize),
          strokeColor: String(defaults.stroke_color || previous.strokeColor),
          strokeWidth: Number(defaults.stroke_width ?? previous.strokeWidth),
          subtitleBackground: Boolean(defaults.subtitle_background_enabled ?? previous.subtitleBackground),
          subtitleBackgroundColor: String(defaults.subtitle_background_color || previous.subtitleBackgroundColor),
          roundedBackground: Boolean(defaults.rounded_subtitle_background ?? previous.roundedBackground),
        }));
      }),
      loadTasks(),
      api<SettingsMap>("/settings").then((data) => {
        setSettings(data);
        const appSettings = data.app || {};
        const provider = String(appSettings.llm_provider || "moonshot");
        const configured = (key: string) => Boolean((appSettings[key] as { configured?: boolean } | undefined)?.configured);
        setSettingsDraft((previous) => ({
          ...previous,
          llmProvider: provider,
          llmApiKey: configured(`${provider}_api_key`) ? "__configured__" : "",
          llmBaseUrl: String(appSettings[`${provider}_base_url`] || previous.llmBaseUrl),
          llmModel: String(appSettings[`${provider}_model_name`] || previous.llmModel),
          pexels: configured("pexels_api_keys") ? "__configured__" : "",
          pixabay: configured("pixabay_api_keys") ? "__configured__" : "",
          coverr: configured("coverr_api_keys") ? "__configured__" : "",
          azureKey: Boolean((data.azure?.speech_key as { configured?: boolean } | undefined)?.configured) ? "__configured__" : "",
          azureRegion: String(data.azure?.speech_region || ""),
          geminiKey: configured("gemini_api_key") ? "__configured__" : "",
          minimaxKey: configured("minimax_api_key") ? "__configured__" : "",
        }));
      }),
    ]).catch((reason) => setError(reason instanceof Error ? reason.message : "Backend is unavailable"));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let active = true;
    const poll = async () => {
      try {
        const task = await api<Task>(`/tasks/${taskId}`);
        if (!active) return;
        setCurrentTask(task);
        if (task.state === PROCESSING) window.setTimeout(poll, 900);
        else { setGenerationMinimized(false); void loadTasks(); }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not read task status");
      }
    };
    void poll();
    return () => { active = false; };
  }, [taskId]);

  useEffect(() => {
    if (!form.matchOrder && form.concat === "sequential") setValue("concat", "random");
  }, [form.matchOrder]);

  const updateProvider = (server: string) => {
    setValue("ttsServer", server);
    const nextVoice = options.voices[server]?.[0] || "";
    setValue("voice", nextVoice);
  };

  const uploadFile = async (endpoint: string, file: File) => {
    const data = new FormData();
    data.append("file", file);
    return api<{ file: string }>(endpoint, { method: "POST", body: data });
  };

  const onMaterials = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    setUploading(true); setError("");
    try {
      const uploaded = await Promise.all(files.map(async (file) => {
        const result = await uploadFile("/video_materials", file);
        return { name: file.name, url: `storage/local_videos/${result.file}` };
      }));
      setMaterials(uploaded);
      setNotice(`${uploaded.length} local material${uploaded.length > 1 ? "s" : ""} attached`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Material upload failed"); }
    finally { setUploading(false); event.target.value = ""; }
  };

  const onAudio = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true); setError("");
    try {
      const result = await uploadFile("/audio_uploads", file);
      setAudioPath(result.file);
      setNotice(`${file.name} ready as voiceover`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Audio upload failed"); }
    finally { setUploading(false); event.target.value = ""; }
  };

  const draftScript = async () => {
    if (!form.subject.trim()) { setError("Add a video subject before drafting the script"); return; }
    setIsGeneratingScript(true); setError("");
    try {
      const scriptResult = await api<{ video_script: string }>("/scripts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_subject: form.subject, video_language: form.language, paragraph_number: form.paragraphNumber, video_script_prompt: form.scriptPrompt, custom_system_prompt: form.systemPrompt }) });
      setValue("script", scriptResult.video_script || "");
      const termsResult = await api<{ video_terms: string[] }>("/terms", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_subject: form.subject, video_script: scriptResult.video_script, amount: 8, match_materials_to_script: form.matchOrder }) });
      setValue("terms", Array.isArray(termsResult.video_terms) ? termsResult.video_terms.join(", ") : String(termsResult.video_terms || ""));
      setNotice("Script and visual beats drafted");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not generate the script"); }
    finally { setIsGeneratingScript(false); }
  };

  const previewVoice = async () => {
    if (!form.voice || !form.script.trim()) {
      setError("Add a script before requesting a voice sample");
      return;
    }
    setError("");
    try {
      const response = await fetch("/api/voice-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: form.script.slice(0, 1000), voice_name: form.voice, voice_rate: form.voiceRate, voice_volume: form.voiceVolume }),
      });
      if (!response.ok) throw new Error("Voice preview failed");
      if (audioPreviewUrl) URL.revokeObjectURL(audioPreviewUrl);
      setAudioPreviewUrl(URL.createObjectURL(await response.blob()));
      setNotice("Voice sample ready");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Voice preview failed");
    }
  };

  const generateVideo = async () => {
    setError(""); setNotice("");
    if (!form.subject.trim() && !form.script.trim()) { setError("Video subject and script cannot both be empty"); return; }
    if (form.source === "local" && !materials.length) { setError("Upload local video materials first"); return; }
    if (form.voiceMode === "upload" && !audioPath) { setError("Upload a voiceover file first"); return; }
    setIsSubmitting(true);
    try {
      const task = await api<{ task_id: string }>("/videos", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        video_subject: form.subject,
        video_script: form.script,
        video_terms: form.terms.split(/[,\n]/).map((term) => term.trim()).filter(Boolean),
        video_aspect: form.aspect,
        video_concat_mode: form.concat,
        video_transition_mode: form.transition || null,
        video_clip_duration: form.clipDuration,
        video_clip_speed: form.clipSpeed,
        match_materials_to_script: form.matchOrder,
        video_count: form.videoCount,
        video_source: form.source,
        video_materials: materials.map((material) => ({ provider: "local", url: material.url, duration: 0 })),
        custom_audio_file: form.voiceMode === "upload" ? audioPath : null,
        video_language: form.language,
        voice_name: form.voiceMode === "none" ? "no-voice" : form.voice,
        voice_volume: form.voiceVolume,
        voice_rate: form.voiceRate,
        bgm_type: form.bgmType,
        bgm_file: form.bgmFile,
        bgm_volume: form.bgmVolume,
        video_music_prompt: form.musicPrompt,
        subtitle_enabled: form.subtitles,
        subtitle_position: form.position,
        custom_position: form.customPosition,
        font_name: form.font,
        text_fore_color: form.fontColor,
        text_background_color: form.subtitleBackground ? form.subtitleBackgroundColor : false,
        rounded_subtitle_background: form.subtitleBackground && form.roundedBackground,
        font_size: form.fontSize,
        stroke_color: form.strokeColor,
        stroke_width: form.strokeWidth,
      }) });
      setTaskId(task.task_id); setCurrentTask({ task_id: task.task_id, state: PROCESSING, progress: 0 });
      setGenerationOpen(true); setGenerationMinimized(false);
      setNotice("Video generation queued");
      void loadTasks();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start generation"); }
    finally { setIsSubmitting(false); }
  };

  const reset = () => { setForm({ ...initialForm, font: options.fonts[0] || "" }); setMaterials([]); setAudioPath(""); setError(""); setNotice(""); };

  const saveSettings = async () => {
    setError("");
    try {
      await Promise.all([
        api("/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section: "app", values: { llm_provider: settingsDraft.llmProvider, [`${settingsDraft.llmProvider}_api_key`]: settingsDraft.llmApiKey.startsWith("__") ? undefined : (settingsDraft.llmApiKey || undefined), [`${settingsDraft.llmProvider}_base_url`]: settingsDraft.llmBaseUrl || undefined, [`${settingsDraft.llmProvider}_model_name`]: settingsDraft.llmModel || undefined, pexels_api_keys: settingsDraft.pexels.startsWith("__") ? undefined : (settingsDraft.pexels || undefined), pixabay_api_keys: settingsDraft.pixabay.startsWith("__") ? undefined : (settingsDraft.pixabay || undefined), coverr_api_keys: settingsDraft.coverr.startsWith("__") ? undefined : (settingsDraft.coverr || undefined), gemini_api_key: settingsDraft.geminiKey.startsWith("__") ? undefined : (settingsDraft.geminiKey || undefined), minimax_api_key: settingsDraft.minimaxKey.startsWith("__") ? undefined : (settingsDraft.minimaxKey || undefined) } }) }),
        api("/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section: "azure", values: { speech_key: settingsDraft.azureKey.startsWith("__") ? undefined : (settingsDraft.azureKey || undefined), speech_region: settingsDraft.azureRegion || undefined } }) }),
      ]);
      setNotice("Runtime settings saved"); setDrawer(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save settings"); }
  };

  const changeLanguage = async (language: string) => {
    setUiLanguage(language);
    try {
      await api("/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section: "ui", values: { language } }) });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save language");
    }
  };

  const selectedProviderLabel = providers.find(([id]) => id === form.ttsServer)?.[1] || form.ttsServer;

  return (
    <main className="flex min-h-screen flex-col overflow-auto px-3 py-3 sm:px-5 lg:h-screen lg:overflow-hidden lg:px-7">
      <header className="studio-header mb-3 flex shrink-0 items-center justify-between border-b border-white/10 px-1 pb-3 sm:px-2">
        <div className="flex min-w-0 items-center gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#ff5b62] to-[#b973ff] text-lg font-black text-white shadow-lg shadow-[#ff5b62]/20">✦</div><div className="min-w-0"><div className="flex items-baseline gap-2"><h1 className="truncate text-xl font-bold tracking-[-.05em] sm:text-2xl">MoneyPrinterTurbo</h1><span className="text-[11px] font-semibold text-[#858b96]">v{options.version || "1.3.4"}</span></div><p className="hidden text-[11px] text-[#858b96] sm:block">Short-form video studio · Next frontend / Python engine</p></div></div>
        <div className="flex items-center gap-2 text-xs"><span className="hidden items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/[.07] px-3 py-2 text-emerald-200 sm:flex"><span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_10px_#34d399]" />Engine connected</span><button className="button" onClick={() => setDrawer("tasks")}><History size={15} /> Tasks <span className="text-[#9899aa]">{tasks.length}</span></button><button className="button" onClick={() => setDrawer("settings")}><Settings size={15} /> Settings</button><select aria-label="Language" className="control !h-9 !min-h-9 !w-32 !py-1.5" value={uiLanguage} onChange={(event) => void changeLanguage(event.target.value)}>{(options.languages || ["en-US"]).map((language) => <option key={language}>{language}</option>)}</select></div>
      </header>

      <section className="studio-grid grid min-h-0 flex-1 gap-3 lg:grid-cols-4">
        <Panel title="Video Script" eyebrow="01" accent>
          <Field label="Video subject"><textarea className="control h-20" placeholder="How AI is changing everyday life" value={form.subject} onChange={(event) => setValue("subject", event.target.value)} /></Field>
          <Field label="Script language"><select className="control" value={form.language} onChange={(event) => setValue("language", event.target.value)}><option value="">Auto Detect</option>{["zh-CN", "zh-HK", "zh-TW", "de-DE", "en-US", "es-ES", "fr-FR", "ru-RU", "vi-VN", "th-TH", "tr-TR"].map((language) => <option key={language}>{language}</option>)}</select></Field>
          <details className="rounded-lg border border-white/10 bg-white/[.02] p-2"><summary className="cursor-pointer text-xs font-semibold text-[#b9bec8]">Advanced script settings</summary><div className="mt-3 grid gap-3"><Range label="Paragraphs" value={form.paragraphNumber} min={1} max={10} step={1} onChange={(value) => setValue("paragraphNumber", value)} /><Field label="Custom script requirements"><textarea className="control h-20" value={form.scriptPrompt} onChange={(event) => setValue("scriptPrompt", event.target.value)} /></Field><Field label="Custom system prompt"><textarea className="control h-28" value={form.systemPrompt} onChange={(event) => setValue("systemPrompt", event.target.value)} /></Field><button className="button button-quiet" onClick={() => setValue("systemPrompt", "")}><RotateCcw size={14} /> Restore default prompt</button></div></details>
          <button className="button button-quiet w-full" onClick={draftScript} disabled={isGeneratingScript}>{isGeneratingScript ? <LoaderCircle className="animate-spin" size={15} /> : <Sparkles size={15} />} {isGeneratingScript ? "Drafting..." : "Generate script & keywords"}</button>
          <Field label="Video script"><textarea className="control min-h-36" placeholder="Write or generate the narration..." value={form.script} onChange={(event) => setValue("script", event.target.value)} /></Field>
          <Field label="Video keywords" help="Comma-separated visual hints"><textarea className="control h-20" placeholder="technology, people, future" value={form.terms} onChange={(event) => setValue("terms", event.target.value)} /></Field>
        </Panel>

        <Panel title="Video Settings" eyebrow="02">
          <Field label="Video source"><select className="control" value={form.source} onChange={(event) => setValue("source", event.target.value as FormState["source"])}><option value="pexels">Pexels</option><option value="pixabay">Pixabay</option><option value="coverr">Coverr</option><option value="local">Local file</option></select></Field>
          {form.source === "local" && <div className="rounded-lg border border-dashed border-white/15 p-3"><label className="button w-full"><Upload size={15} /> {uploading ? "Uploading..." : "Upload local materials"}<input className="hidden" type="file" multiple accept={options.local_material_extensions.map((extension) => `.${extension}`).join(",")} onChange={onMaterials} /></label>{materials.length > 0 && <div className="mt-2 grid gap-1">{materials.map((material) => <div key={material.url} className="flex items-center gap-2 text-[11px] text-[#aeb4bf]"><FileVideo size={13} />{material.name}</div>)}</div>}</div>}
          <Field label="Video concatenation"><select className="control" value={form.concat} disabled={form.matchOrder} onChange={(event) => setValue("concat", event.target.value as FormState["concat"])}><option value="random">Random (Recommended)</option><option value="sequential">Sequential</option></select></Field>
          <CheckBox label="Match visuals to script order" checked={form.matchOrder} onChange={(checked) => { setValue("matchOrder", checked); if (checked) setValue("concat", "sequential"); }} />
          <Field label="Video transition"><select className="control" value={form.transition} onChange={(event) => setValue("transition", event.target.value)}><option value="">None</option><option>Shuffle</option><option>FadeIn</option><option>FadeOut</option><option>SlideIn</option><option>SlideOut</option><option>ZoomIn</option><option>ZoomOut</option></select></Field>
          <Field label="Video aspect ratio"><div className="segmented">{([["9:16", "Portrait"], ["16:9", "Landscape"], ["1:1", "Square"]] as const).map(([value, label]) => <button key={value} className={form.aspect === value ? "active" : ""} onClick={() => setValue("aspect", value)}>{label}<span className="ml-1 text-[10px] opacity-60">{value}</span></button>)}</div></Field>
          <Range label="Maximum clip duration" value={form.clipDuration} min={2} max={10} step={1} suffix="s" onChange={(value) => setValue("clipDuration", value)} />
          <Range label="Clip speed" value={form.clipSpeed} min={0.5} max={2} step={0.05} suffix="×" onChange={(value) => setValue("clipSpeed", value)} />
          <Field label="Videos per run"><select className="control" value={form.videoCount} onChange={(event) => setValue("videoCount", Number(event.target.value))}>{[1, 2, 3, 4, 5].map((count) => <option key={count}>{count}</option>)}</select></Field>
          <Field label="Video encoder"><select className="control" value={form.videoCodec} onChange={async (event) => { const value = event.target.value; setValue("videoCodec", value); try { await api("/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section: "app", values: { video_codec: value === "__default__" ? "" : value } }) }); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save video encoder"); } }}><option value="__default__">Default video encoder</option><option value="libx264">libx264 (CPU)</option><option value="h264_nvenc">NVIDIA NVENC</option><option value="h264_amf">AMD AMF</option><option value="h264_qsv">Intel QSV</option><option value="h264_mf">Windows MediaFoundation</option><option value="h264_videotoolbox">macOS VideoToolbox</option></select></Field>
        </Panel>

        <Panel title="Audio Settings" eyebrow="03">
          <Field label="Voiceover mode"><div className="segmented">{([["tts", "Automatic"], ["upload", "Upload"], ["none", "None"]] as const).map(([value, label]) => <button key={value} className={form.voiceMode === value ? "active" : ""} onClick={() => setValue("voiceMode", value)}>{label}</button>)}</div></Field>
          {form.voiceMode === "tts" && <><Field label="Voiceover service"><select className="control" value={form.ttsServer} onChange={(event) => updateProvider(event.target.value)}>{providers.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field><Field label={`Voice · ${selectedProviderLabel}`}><select className="control" value={form.voice} onChange={(event) => setValue("voice", event.target.value)}>{voices.length ? voices.map((voice) => <option key={voice} value={voice}>{voice}</option>) : <option value="">No voices loaded</option>}</select></Field><div className="grid grid-cols-2 gap-3"><Range label="Volume" value={form.voiceVolume} min={0.6} max={5} step={0.1} suffix="×" onChange={(value) => setValue("voiceVolume", value)} /><Range label="Speed" value={form.voiceRate} min={0.8} max={2} step={0.1} suffix="×" onChange={(value) => setValue("voiceRate", value)} /></div><button className="button w-full" onClick={previewVoice}><Play size={14} /> Voice sample</button>{audioPreviewUrl && <audio className="w-full" controls src={audioPreviewUrl} />}</>}
          {form.voiceMode === "upload" && <div className="rounded-lg border border-dashed border-white/15 p-3"><label className="button w-full"><FileAudio size={15} /> {uploading ? "Uploading..." : "Upload voiceover"}<input className="hidden" type="file" accept={options.audio_extensions.map((extension) => `.${extension.replace(".", "")}`).join(",")} onChange={onAudio} /></label>{audioPath && <p className="mt-2 text-[11px] text-emerald-200">Voiceover file ready</p>}</div>}
          <div className="mt-1 border-t border-white/10 pt-3"><Field label="Background music"><select className="control" value={form.bgmType} onChange={(event) => setValue("bgmType", event.target.value)}><option value="random">Random background music</option><option value="none">No background music</option><option value="custom">Custom music</option><option value="sonilo">Sonilo music</option><option value="elevenlabs">ElevenLabs music</option></select></Field>{form.bgmType === "custom" && <><select className="control mt-2" value={form.bgmFile} onChange={(event) => setValue("bgmFile", event.target.value)}><option value="">Choose uploaded or built-in music</option>{options.songs.map((song) => <option key={song}>{song}</option>)}</select><label className="button button-quiet mt-2 w-full"><Upload size={14} /> Upload music<input className="hidden" type="file" accept="audio/*" onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; try { const result = await uploadFile("/musics", file); setValue("bgmFile", result.file); setNotice("Background music uploaded"); } catch (reason) { setError(reason instanceof Error ? reason.message : "Music upload failed"); } }} /></label></>}<Range label="Music volume" value={form.bgmVolume} min={0} max={1} step={0.05} suffix="×" onChange={(value) => setValue("bgmVolume", value)} />{(form.bgmType === "sonilo" || form.bgmType === "elevenlabs") && <Field label="Music prompt"><input className="control" value={form.musicPrompt} onChange={(event) => setValue("musicPrompt", event.target.value)} placeholder="Mood, tempo, atmosphere" /></Field>}</div>
        </Panel>

        <Panel title="Subtitle Settings" eyebrow="04">
          <CheckBox label="Enable subtitles" checked={form.subtitles} onChange={(checked) => setValue("subtitles", checked)} strong />
          <Field label="Font"><select className="control" disabled={!form.subtitles} value={form.font} onChange={(event) => setValue("font", event.target.value)}>{options.fonts.map((font) => <option key={font}>{font}</option>)}</select></Field>
          <Field label="Position"><select className="control" disabled={!form.subtitles} value={form.position} onChange={(event) => setValue("position", event.target.value as FormState["position"])}><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option><option value="custom">Custom</option></select></Field>
          {form.position === "custom" && <Range label="Custom position from top" value={form.customPosition} min={0} max={100} step={1} suffix="%" onChange={(value) => setValue("customPosition", value)} />}
          <div className="grid grid-cols-[.42fr_.58fr] gap-3"><Field label="Color"><input className="control h-10 p-1" type="color" disabled={!form.subtitles} value={form.fontColor} onChange={(event) => setValue("fontColor", event.target.value)} /></Field><Range label="Font size" value={form.fontSize} min={30} max={100} step={1} suffix="px" onChange={(value) => setValue("fontSize", value)} /></div>
          <div className="grid grid-cols-[.42fr_.58fr] gap-3"><Field label="Outline"><input className="control h-10 p-1" type="color" disabled={!form.subtitles} value={form.strokeColor} onChange={(event) => setValue("strokeColor", event.target.value)} /></Field><Range label="Outline width" value={form.strokeWidth} min={0} max={10} step={0.5} suffix="px" onChange={(value) => setValue("strokeWidth", value)} /></div>
          <CheckBox label="Subtitle background" checked={form.subtitleBackground} onChange={(checked) => setValue("subtitleBackground", checked)} /><div className="grid grid-cols-2 gap-3"><Field label="Background color"><input className="control h-10 p-1" type="color" disabled={!form.subtitleBackground} value={form.subtitleBackgroundColor} onChange={(event) => setValue("subtitleBackgroundColor", event.target.value)} /></Field><CheckBox label="Rounded" checked={form.roundedBackground} disabled={!form.subtitleBackground} onChange={(checked) => setValue("roundedBackground", checked)} /></div>
          <div className="rounded-lg border border-white/10 bg-[#0f1216] p-4 text-center text-xl" style={{ color: form.fontColor, fontSize: `${Math.min(form.fontSize, 42)}px`, textShadow: `${form.strokeWidth}px ${form.strokeWidth}px 0 ${form.strokeColor}` }}>Your captions look like this</div>
          <button className="button button-quiet w-full" onClick={() => setForm((previous) => ({ ...previous, ...initialForm, font: previous.font }))}><RotateCcw size={14} /> Restore subtitle defaults</button>
        </Panel>
      </section>

      {error && <div className="mt-2 rounded-xl border border-rose-400/25 bg-rose-400/[.08] px-4 py-2 text-xs text-rose-100">{error}</div>}
      {notice && !error && <div className="mt-2 rounded-xl border border-emerald-400/20 bg-emerald-400/[.06] px-4 py-2 text-xs text-emerald-100">{notice}</div>}
      <footer className="studio-footer mt-3 flex shrink-0 flex-wrap items-center gap-3 border-t border-white/10 px-1 pt-3 sm:px-2"><div className="min-w-[180px] flex-1"><div className="flex items-center justify-between text-xs"><span className="font-semibold text-white">{taskStatus(currentTask)}</span><span className="text-[#ff8f94]">{currentTask ? `${progress}%` : "—"}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[.08]"><div className="h-full rounded-full bg-gradient-to-r from-[#ff5b62] to-[#b973ff] transition-all duration-500" style={{ width: `${progress}%` }} /></div></div>{currentVideo && <a className="button" href={assetUrl(currentVideo)} download><Download size={14} /> Download result</a>}<button className="button" onClick={reset}><RotateCcw size={14} /> Reset</button><button className="button button-primary px-6" onClick={generateVideo} disabled={isSubmitting}>{isSubmitting ? <LoaderCircle className="animate-spin" size={15} /> : <WandSparkles size={15} />} {isSubmitting ? "Starting..." : "Generate video ↗"}</button></footer>
      {currentVideo && <section className="mt-3 rounded-2xl border border-white/10 bg-[#15181d]/90 p-4"><div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-bold">Generated result</h2><a className="text-xs text-[#ff9b9f]" href={assetUrl(currentVideo)} target="_blank" rel="noreferrer">Open file ↗</a></div><video className="max-h-[420px] w-full rounded-xl bg-black object-contain" controls src={assetUrl(currentVideo)} /></section>}

      {drawer === "tasks" && <TaskDrawer tasks={tasks} currentTaskId={taskId} onClose={() => setDrawer(null)} onRefresh={loadTasks} onOpen={(task) => { setTaskId(task.task_id); setCurrentTask(task); setDrawer(null); }} />}
      {drawer === "settings" && <CompactSettingsDrawer draft={settingsDraft} setDraft={setSettingsDraft} settings={settings} llmProviders={options.llm_providers || []} onClose={() => setDrawer(null)} onSave={saveSettings} />}
      {generationOpen && currentTask && !generationMinimized && <GenerationDialog task={currentTask} onMinimize={() => setGenerationMinimized(true)} onClose={() => setGenerationOpen(false)} />}
      {generationOpen && currentTask && generationMinimized && <button className="generation-pill fixed bottom-5 right-5 z-40 flex items-center gap-3 rounded-full border border-[#ff5b62]/40 bg-[#17141b]/95 px-4 py-3 text-left shadow-2xl shadow-black/40 backdrop-blur" onClick={() => setGenerationMinimized(false)}><span className="grid h-8 w-8 place-items-center rounded-full bg-[#ff5b62]/15 text-[#ff9b9f]"><LoaderCircle className="animate-spin" size={16} /></span><span><span className="block text-xs font-bold text-white">Generation in progress</span><span className="block text-[11px] text-[#aeb4bf]">{progress}% · {currentTask.stage_label || "Working"}</span></span><Maximize2 size={14} className="ml-2 text-[#9899aa]" /></button>}
    </main>
  );
}

function Panel({ title, eyebrow, accent, children }: { title: string; eyebrow: string; accent?: boolean; children: ReactNode }) {
  return <section className={`studio-panel flex min-h-0 flex-col p-3.5 ${accent ? "studio-panel-accent" : ""}`}><div className="mb-3 flex shrink-0 items-center justify-between border-b border-white/10 pb-2.5"><div className="flex items-center gap-2"><span className="grid h-5 w-5 place-items-center rounded-md bg-white/[.07] text-[9px] font-bold text-[#9899aa]">{eyebrow}</span><h2 className="text-sm font-bold tracking-[-.02em] text-white">{title}</h2></div><span className="h-1.5 w-1.5 rounded-full bg-[#ff5b62] opacity-70" /></div><div className="panel-scroll min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">{children}</div></section>;
}

function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) { return <label className="field"><span className="field-label">{label}</span>{children}{help && <span className="field-help">{help}</span>}</label>; }
function CheckBox({ label, checked, onChange, disabled, strong }: { label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean; strong?: boolean }) { return <label className={`check ${strong ? "text-sm font-semibold text-white" : ""}`}><input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />{label}</label>; }
function Range({ label, value, min, max, step, suffix = "", onChange }: { label: string; value: number; min: number; max: number; step: number; suffix?: string; onChange: (value: number) => void }) { return <div className="range-row"><div className="range-head"><span>{label}</span><span>{Number.isInteger(value) ? value : value.toFixed(2)}{suffix}</span></div><input className="range" type="range" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></div>; }

function TaskDrawer({ tasks, currentTaskId, onClose, onRefresh, onOpen }: { tasks: Task[]; currentTaskId: string; onClose: () => void; onRefresh: () => Promise<void>; onOpen: (task: Task) => void }) {
  const [busy, setBusy] = useState("");
  const remove = async (task: Task) => { setBusy(task.task_id); try { await api(`/tasks/${task.task_id}`, { method: "DELETE" }); await onRefresh(); } catch { /* the main screen will remain usable */ } finally { setBusy(""); } };
  return <aside className="fixed inset-y-0 right-0 z-20 w-full max-w-md border-l border-white/10 bg-[#111419] p-5 shadow-2xl"><div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[.2em] text-[#ff8f94]">Recent work</p><h2 className="mt-1 text-xl font-bold">Task manager</h2></div><button className="button" onClick={onClose}><X size={16} /></button></div><div className="mt-5 grid gap-2">{tasks.length === 0 && <p className="rounded-lg border border-dashed border-white/10 p-4 text-sm text-[#858b96]">Your generated videos will appear here.</p>}{tasks.map((task) => <div key={task.task_id} className={`rounded-xl border p-3 ${task.task_id === currentTaskId ? "border-[#ff5b62]/45 bg-[#ff5b62]/[.06]" : "border-white/10 bg-white/[.02]"}`}><div className="flex items-start justify-between gap-3"><button className="min-w-0 text-left" onClick={() => onOpen(task)}><p className="truncate text-sm font-semibold">{taskTitle(task)}</p><p className="mt-1 text-[11px] text-[#858b96]">{task.state === COMPLETE ? "Complete" : task.state === FAILED ? "Failed" : "Processing"} · {task.progress || 0}%</p></button><button className="button !min-h-8 !p-2" disabled={busy === task.task_id || task.state === PROCESSING} onClick={() => remove(task)} title="Delete task">{busy === task.task_id ? <LoaderCircle className="animate-spin" size={14} /> : <Trash2 size={14} />}</button></div><div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[.08]"><div className="h-full bg-[#ff5b62]" style={{ width: `${task.progress || 0}%` }} /></div></div>)}</div><button className="button mt-5 w-full" onClick={onRefresh}><RefreshCw size={14} /> Refresh task history</button></aside>;
}

function fallbackGenerationEvents(task: Task): TaskEvent[] {
  const steps = [
    ["queue", "Generation queued", 0],
    ["script", "Writing the narration script", 5],
    ["terms", "Planning visual search beats", 10],
    ["audio", "Creating the voiceover", 20],
    ["subtitle", "Designing captions", 30],
    ["materials", "Collecting footage", 40],
    ["render", "Rendering the final video", 50],
  ] as const;
  return steps.map(([stage, message, progress]) => ({ stage, message, progress, level: task.state === FAILED && task.failed_stage === stage ? "error" : "info" }));
}

function GenerationDialog({ task, onMinimize, onClose }: { task: Task; onMinimize: () => void; onClose: () => void }) {
  const events = task.events?.length ? task.events : fallbackGenerationEvents(task);
  const isProcessing = task.state === PROCESSING;
  const isComplete = task.state === COMPLETE;
  const isFailed = task.state === FAILED;
  const currentLabel = task.stage_label || (isComplete ? "Your video is ready" : isFailed ? task.error || "Generation failed" : "Preparing your video");
  const eventIcon = (event: TaskEvent, index: number) => {
    if (event.level === "error") return <AlertCircle size={16} className="text-rose-300" />;
    if (isComplete || index < events.length - 1 || (event.progress || 0) < (task.progress || 0)) return <CheckCircle2 size={16} className="text-emerald-300" />;
    if (isProcessing && index === events.length - 1) return <LoaderCircle size={16} className="animate-spin text-[#ff9b9f]" />;
    return <span className="h-2.5 w-2.5 rounded-full border border-[#6d7280]" />;
  };
  return <aside className="generation-popup fixed bottom-5 right-5 z-40 flex max-h-[min(720px,calc(100vh-2rem))] w-[min(460px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-white/15 bg-[#15131b]/[.98] shadow-2xl shadow-black/50 backdrop-blur-xl" role="dialog" aria-label="Video generation progress">
    <div className="flex shrink-0 items-start justify-between border-b border-white/10 px-5 py-4"><div className="flex items-center gap-3"><span className={`grid h-10 w-10 place-items-center rounded-xl ${isComplete ? "bg-emerald-400/15 text-emerald-300" : isFailed ? "bg-rose-400/15 text-rose-300" : "bg-gradient-to-br from-[#ff5b62] to-[#b973ff] text-white"}`}>{isComplete ? <CheckCircle2 size={20} /> : isFailed ? <AlertCircle size={20} /> : <LoaderCircle className="animate-spin" size={20} />}</span><div><p className="text-[10px] font-bold uppercase tracking-[.18em] text-[#ff8f94]">{isProcessing ? "Live generation" : isComplete ? "Generation complete" : "Generation stopped"}</p><h2 className="mt-1 text-base font-bold text-white">{isProcessing ? "Creating your short" : isComplete ? "Your video is ready" : "Generation needs attention"}</h2></div></div><div className="flex items-center gap-1"><button className="button !min-h-8 !p-2" onClick={onMinimize} title="Minimize"><Minimize2 size={14} /></button><button className="button !min-h-8 !p-2" onClick={onClose} title="Close"><span className="text-base leading-none">×</span></button></div></div>
    <div className="shrink-0 px-5 pt-4"><div className="flex items-end justify-between gap-4"><div><p className="text-sm font-semibold text-white">{currentLabel}</p><p className="mt-1 text-xs text-[#858b96]">The Python engine is working in the background.</p></div><span className="text-lg font-bold text-[#ff9b9f]">{task.progress || 0}%</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-white/[.08]"><div className="h-full rounded-full bg-gradient-to-r from-[#ff5b62] via-[#ff8f94] to-[#b973ff] transition-all duration-700" style={{ width: `${task.progress || 0}%` }} /></div></div>
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{isComplete && task.videos?.[0] && <div className="mb-5 overflow-hidden rounded-xl border border-white/10 bg-black"><div className="flex items-center justify-between border-b border-white/10 bg-white/[.03] px-3 py-2"><p className="text-[10px] font-bold uppercase tracking-[.18em] text-[#858b96]">Generated preview</p><a className="text-[11px] font-semibold text-[#ff9b9f]" href={assetUrl(task.videos[0])} target="_blank" rel="noreferrer">Open file ↗</a></div><video className="max-h-72 w-full bg-black object-contain" controls playsInline src={assetUrl(task.videos[0])} /></div>}<div className="mb-3 flex items-center justify-between"><p className="text-[10px] font-bold uppercase tracking-[.18em] text-[#858b96]">Execution timeline</p><span className="text-[11px] text-[#666d79]">{events.length} steps</span></div><div className="relative grid gap-1 before:absolute before:bottom-4 before:left-[7px] before:top-4 before:w-px before:bg-white/10">{events.map((event, index) => <div key={event.id || `${event.stage}-${index}`} className={`relative flex gap-3 rounded-xl px-2 py-2.5 ${index === events.length - 1 && isProcessing ? "bg-[#ff5b62]/[.08]" : ""}`}><span className="relative z-10 grid h-5 w-5 shrink-0 place-items-center bg-[#15131b]">{eventIcon(event, index)}</span><div className="min-w-0 flex-1"><p className={`text-xs ${index === events.length - 1 && isProcessing ? "font-semibold text-white" : "text-[#c8ccd5]"}`}>{event.message}</p><div className="mt-1 flex items-center gap-2 text-[10px] text-[#666d79]"><span>{event.stage}</span>{event.timestamp && <><span>·</span><span>{new Date(event.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span></>}</div></div>{event.progress !== undefined && <span className="pt-0.5 text-[10px] text-[#858b96]">{event.progress}%</span>}</div>)}</div></div>
    <div className="flex shrink-0 items-center justify-between border-t border-white/10 px-5 py-3"><p className="text-[11px] text-[#858b96]">You can keep working while this runs.</p>{isComplete && task.videos?.[0] && <a className="button button-primary !min-h-8 !px-3" href={assetUrl(task.videos[0])} target="_blank" rel="noreferrer">Open video ↗</a>}</div>
  </aside>;
}

function SettingsDrawer({ draft, setDraft, settings, onClose, onSave }: { draft: { llmProvider: string; llmApiKey: string; llmBaseUrl: string; llmModel: string; pexels: string; pixabay: string; coverr: string; azureKey: string; azureRegion: string; geminiKey: string; minimaxKey: string }; setDraft: (value: { llmProvider: string; llmApiKey: string; llmBaseUrl: string; llmModel: string; pexels: string; pixabay: string; coverr: string; azureKey: string; azureRegion: string; geminiKey: string; minimaxKey: string }) => void; settings: SettingsMap; onClose: () => void; onSave: () => Promise<void> }) {
  const update = (key: keyof typeof draft, value: string) => setDraft({ ...draft, [key]: value });
  const configured = (section: string, key: string) => Boolean((settings[section]?.[key] as { configured?: boolean } | undefined)?.configured);
  const secretValue = (value: string) => value.startsWith("__") ? "" : value;
  const status = (section: string, key: string, value: string) => value.startsWith("__") || configured(section, key) ? " · configured" : "";
  return <aside className="fixed inset-y-0 right-0 z-20 w-full max-w-xl overflow-y-auto border-l border-white/10 bg-[#111419] p-5 shadow-2xl"><div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[.2em] text-[#ff8f94]">Runtime configuration</p><h2 className="mt-1 text-xl font-bold">Settings</h2></div><button className="button" onClick={onClose}><X size={16} /></button></div><p className="mt-3 rounded-lg border border-amber-400/20 bg-amber-400/[.05] p-3 text-xs leading-5 text-amber-100">Saved keys remain on the Python engine and are never sent back to the browser. A “configured” label means the existing key is still active; enter a new value only when rotating it.</p><div className="mt-5 grid gap-4"><section className="grid gap-3"><h3 className="text-xs font-bold uppercase tracking-[.15em] text-[#9899aa]">Language model</h3><Field label="Provider"><input className="control" value={draft.llmProvider} onChange={(event) => update("llmProvider", event.target.value)} placeholder="moonshot, openai, gemini..." /></Field><Field label={`API key${status("app", `${draft.llmProvider}_api_key`, draft.llmApiKey)}`}><input className="control" type="password" value={secretValue(draft.llmApiKey)} placeholder={draft.llmApiKey.startsWith("__") ? "Saved key is active" : "Enter API key"} onChange={(event) => update("llmApiKey", event.target.value)} /></Field><Field label="Base URL"><input className="control" value={draft.llmBaseUrl} onChange={(event) => update("llmBaseUrl", event.target.value)} placeholder="https://api.openai.com/v1" /></Field><Field label="Model name"><input className="control" value={draft.llmModel} onChange={(event) => update("llmModel", event.target.value)} placeholder="gpt-4o-mini" /></Field></section><section className="grid gap-3"><h3 className="text-xs font-bold uppercase tracking-[.15em] text-[#9899aa]">Material providers</h3><Field label={`Pexels API key${status("app", "pexels_api_keys", draft.pexels)}`}><input className="control" type="password" value={secretValue(draft.pexels)} placeholder={draft.pexels.startsWith("__") ? "Saved key is active" : "Enter API key"} onChange={(event) => update("pexels", event.target.value)} /></Field><Field label={`Pixabay API key${status("app", "pixabay_api_keys", draft.pixabay)}`}><input className="control" type="password" value={secretValue(draft.pixabay)} placeholder={draft.pixabay.startsWith("__") ? "Saved key is active" : "Enter API key"} onChange={(event) => update("pixabay", event.target.value)} /></Field><Field label={`Coverr API key${status("app", "coverr_api_keys", draft.coverr)}`}><input className="control" type="password" value={secretValue(draft.coverr)} placeholder={draft.coverr.startsWith("__") ? "Saved key is active" : "Enter API key"} onChange={(event) => update("coverr", event.target.value)} /></Field></section><section className="grid gap-3"><h3 className="text-xs font-bold uppercase tracking-[.15em] text-[#9899aa]">Voice providers</h3><div className="grid grid-cols-2 gap-3"><Field label={`Azure speech key${status("azure", "speech_key", draft.azureKey)}`}><input className="control" type="password" value={secretValue(draft.azureKey)} placeholder={draft.azureKey.startsWith("__") ? "Saved key is active" : "Enter API key"} onChange={(event) => update("azureKey", event.target.value)} /></Field><Field label="Azure region"><input className="control" value={draft.azureRegion} onChange={(event) => update("azureRegion", event.target.value)} /></Field></div><Field label={`Gemini TTS key${status("app", "gemini_api_key", draft.geminiKey)}`}><input className="control" type="password" value={secretValue(draft.geminiKey)} placeholder={draft.geminiKey.startsWith("__") ? "Saved key is active" : "Enter API key"} onChange={(event) => update("geminiKey", event.target.value)} /></Field><Field label={`MiniMax key${status("app", "minimax_api_key", draft.minimaxKey)}`}><input className="control" type="password" value={secretValue(draft.minimaxKey)} placeholder={draft.minimaxKey.startsWith("__") ? "Saved key is active" : "Enter API key"} onChange={(event) => update("minimaxKey", event.target.value)} /></Field></section></div><div className="mt-6 flex justify-end gap-2"><button className="button" onClick={onClose}>Cancel</button><button className="button button-primary" onClick={onSave}><Check size={14} /> Save settings</button></div></aside>;
}

type SettingsDraft = {
  llmProvider: string;
  llmApiKey: string;
  llmBaseUrl: string;
  llmModel: string;
  pexels: string;
  pixabay: string;
  coverr: string;
  azureKey: string;
  azureRegion: string;
  geminiKey: string;
  minimaxKey: string;
};

function CompactSettingsDrawer({ draft, setDraft, settings, llmProviders, onClose, onSave }: { draft: SettingsDraft; setDraft: (value: SettingsDraft) => void; settings: SettingsMap; llmProviders: NonNullable<UiOptions["llm_providers"]>; onClose: () => void; onSave: () => Promise<void> }) {
  const [tab, setTab] = useState<"model" | "materials" | "voice">("model");
  const update = (key: keyof SettingsDraft, value: string) => setDraft({ ...draft, [key]: value });
  const configured = (section: string, key: string) => Boolean((settings[section]?.[key] as { configured?: boolean } | undefined)?.configured);
  const secretValue = (value: string) => value.startsWith("__") ? "" : value;
  const status = (section: string, key: string, value: string) => value.startsWith("__") || configured(section, key) ? " · active" : "";
  const input = (key: keyof SettingsDraft, section: string, configKey: string, label: string) => <Field label={`${label}${status(section, configKey, draft[key])}`}><input className="control" type="password" value={secretValue(draft[key])} placeholder={draft[key].startsWith("__") ? "Saved key is active" : "Enter API key"} onChange={(event) => update(key, event.target.value)} /></Field>;
  const changeProvider = (providerId: string) => {
    const provider = llmProviders.find((item) => item.id === providerId);
    const appSettings = settings.app || {};
    const providerConfigured = Boolean((appSettings[`${providerId}_api_key`] as { configured?: boolean } | undefined)?.configured);
    setDraft({
      ...draft,
      llmProvider: providerId,
      llmApiKey: providerConfigured ? "__configured__" : "",
      llmBaseUrl: String(appSettings[`${providerId}_base_url`] || provider?.default_base_url || ""),
      llmModel: String(appSettings[`${providerId}_model_name`] || provider?.default_model || ""),
    });
  };

  return <aside className="settings-drawer fixed inset-y-0 right-0 z-20 flex w-full max-w-xl flex-col border-l border-white/10 bg-[#111419] p-5 shadow-2xl">
    <div className="flex shrink-0 items-start justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[.2em] text-[#ff8f94]">Runtime configuration</p><h2 className="mt-1 text-xl font-bold">Settings</h2></div><button className="button" onClick={onClose}><X size={16} /></button></div>
    <p className="mt-3 shrink-0 rounded-lg border border-amber-400/20 bg-amber-400/[.05] p-3 text-xs leading-5 text-amber-100">Saved keys stay on the Python engine. Active credentials are shown as status, never exposed as plaintext.</p>
    <nav className="settings-tabs mt-4 grid shrink-0 grid-cols-3 border-y border-white/10 py-2"><button className={tab === "model" ? "active" : ""} onClick={() => setTab("model")}>Language model</button><button className={tab === "materials" ? "active" : ""} onClick={() => setTab("materials")}>Materials</button><button className={tab === "voice" ? "active" : ""} onClick={() => setTab("voice")}>Voice providers</button></nav>
    <div className="settings-content mt-4 min-h-0 flex-1 overflow-y-auto pr-2">
      {tab === "model" && <section className="grid gap-3"><p className="text-xs text-[#858b96]">The selected provider is shared with the Python CLI and generation engine.</p><Field label="Provider"><select className="control" value={draft.llmProvider} onChange={(event) => changeProvider(event.target.value)}>{llmProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></Field>{input("llmApiKey", "app", `${draft.llmProvider}_api_key`, "API key")}<Field label="Base URL"><input className="control" value={draft.llmBaseUrl} onChange={(event) => update("llmBaseUrl", event.target.value)} placeholder="https://api.openai.com/v1" /></Field><Field label="Model name"><input className="control" value={draft.llmModel} onChange={(event) => update("llmModel", event.target.value)} placeholder="gpt-4o-mini" /></Field></section>}
      {tab === "materials" && <section className="grid gap-3"><p className="text-xs text-[#858b96]">Material keys are used when the selected video source searches online footage.</p>{input("pexels", "app", "pexels_api_keys", "Pexels API key")}{input("pixabay", "app", "pixabay_api_keys", "Pixabay API key")}{input("coverr", "app", "coverr_api_keys", "Coverr API key")}</section>}
      {tab === "voice" && <section className="grid gap-3"><p className="text-xs text-[#858b96]">Voice provider credentials power automatic narration and voice samples.</p><div className="grid grid-cols-2 gap-3">{input("azureKey", "azure", "speech_key", "Azure speech key")}<Field label="Azure region"><input className="control" value={draft.azureRegion} onChange={(event) => update("azureRegion", event.target.value)} placeholder="eastus" /></Field></div>{input("geminiKey", "app", "gemini_api_key", "Gemini TTS key")}{input("minimaxKey", "app", "minimax_api_key", "MiniMax key")}</section>}
    </div>
    <div className="mt-4 flex shrink-0 justify-end gap-2 border-t border-white/10 pt-3"><button className="button" onClick={onClose}>Cancel</button><button className="button button-primary" onClick={onSave}><Check size={14} /> Save settings</button></div>
  </aside>;
}
