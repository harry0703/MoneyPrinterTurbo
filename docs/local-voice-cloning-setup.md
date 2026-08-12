# Local Voice Cloning Setup for MoneyPrinterTurbo

Reviewed: July 12, 2026

> Status: unsupported local experiment. This workspace is not part of the
> campaign pipeline, is not covered by product support, and must not be used
> with a person's voice without explicit permission. Tool and model licenses,
> provenance, retention behavior, and current system requirements must be
> rechecked from their official sources before any download or real use.

This is a local-first proof-of-concept plan for a Windows 11 laptop with modest CPU-only hardware, such as a Lenovo ThinkPad T590 with an Intel i5-8365U. The priority is reliable, slow-but-working generation, not GPU throughput.

Do not put private voice samples, generated voice files, API keys, or cloned-voice model caches in git.

## Safest Place In This Project

Use a sidecar workflow first:

- `docs/local-voice-cloning-setup.md`: this guide.
- `tools/local-voice/check-local-voice.ps1`: local readiness and endpoint checks.
- `local_voice/`: private working folders for reference clips, script snippets, and outputs.

MoneyPrinterTurbo already has a Chatterbox TTS integration in:

- `app/services/voice.py`, via an OpenAI-compatible `POST /audio/speech` client.
- `webui/Main.py`, where "Chatterbox TTS" appears as a selectable TTS server.
- `config.example.toml`, under `[chatterbox]`.

So the safest first step is not to edit MoneyPrinterTurbo. Generate narration outside the app, save it as a WAV or MP3, then manually import or replace narration in the MoneyPrinterTurbo output workflow. Once the audio workflow is proven, integration can reuse the existing Chatterbox hook instead of adding a second voice-cloning path.

## Recommended First Path

Start with Voicebox.sh as a local GUI/API proof of concept.

Why this is the simplest first path for this machine:

- It ships a Windows desktop build with no project-level Python or CUDA setup required.
- It provides a local REST API at `http://127.0.0.1:17493`.
- It can manage voice profiles and engines through a GUI before any MoneyPrinterTurbo integration work.
- It avoids changing this repo while you learn the quality/speed limits of the laptop.

Expected tradeoff: CPU-only generation may be slow, and some engines may be impractical without GPU acceleration. Treat the first test as a short narration clip, not a batch workflow.

If Voicebox is too slow or cannot use a CPU-friendly engine on this laptop, the next practical path is an OpenAI-compatible Chatterbox server because this MoneyPrinterTurbo checkout already knows how to call that style of endpoint.

## Option A: Voicebox.sh

Official sources:

- Website: https://voicebox.sh/
- Source/releases: https://github.com/jamiepine/voicebox
- Local API docs advertised from the app/site: `http://127.0.0.1:17493`

What it gives you:

- GUI for cloning and managing voice profiles.
- Local API endpoints for generation, profiles, model status, and history.
- Multiple engines behind one desktop workflow.
- Windows MSI download.

Fit for this laptop:

- Best first experiment because setup friction is low.
- Do not assume every model will run acceptably on CPU.
- Choose the smallest/fastest available engine first.
- Keep first test text under 20 seconds of speech.

MoneyPrinterTurbo fit:

- For now, export a WAV/MP3 from Voicebox and manually replace/import narration.
- Later, add a tiny adapter that calls Voicebox `/generate` and writes the returned audio into the task folder.

## Option B: Chatterbox / OpenAI-Compatible Server

Official and common sources:

- Resemble AI Chatterbox: https://github.com/resemble-ai/chatterbox
- OpenAI-compatible community API wrapper: https://github.com/travisvn/chatterbox-tts-api

What it gives you:

- Open-source TTS with zero-shot voice cloning.
- Chatterbox model family with smaller Turbo and 500M-class multilingual models.
- API wrappers that expose OpenAI-style `/v1/audio/speech`.

Fit for this laptop:

- More setup risk than Voicebox.
- CPU can work, but expect slow generation and possible dependency friction.
- Community API docs recommend 8 GB+ memory and note CPU mode is slower.
- Do not download models until you intentionally choose the engine and confirm disk/RAM budget.

MoneyPrinterTurbo fit:

- This is already the closest integration match. The project can call:

```toml
[chatterbox]
base_url = "http://127.0.0.1:4123/v1"
api_key = ""
model_id = "chatterbox"
voices = ["default-Female"]
```

Then select "Chatterbox TTS" in the WebUI.

Important limitation: Chatterbox does not return word-level timestamps to MoneyPrinterTurbo's current client. For tighter subtitle sync, use `subtitle_provider = "whisper"` after accepting the CPU/model-size cost, or keep `edge` and manually review subtitles.

## Option C: Direct Qwen/Qwen3-TTS

Official source:

- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS

What it gives you:

- Open-source Qwen TTS models with streaming speech generation, voice design, and vivid voice cloning.
- Research-grade model family under Apache-2.0.

Fit for this laptop:

- Not recommended as the first local path on this CPU-only machine.
- More moving parts than Voicebox and likely heavier model/runtime requirements.
- Good later research option if you move generation to a stronger workstation or rented GPU.

MoneyPrinterTurbo fit:

- There is no direct Qwen3-TTS integration in this checkout.
- Best future route would be to wrap Qwen3-TTS behind an OpenAI-compatible `/audio/speech` endpoint, then reuse the existing Chatterbox-style integration pattern.

## Local Folder Layout

Use this layout for private experiments:

```text
local_voice/
  reference/  # Put your private reference voice clips here.
  scripts/    # Put short narration text files here.
  output/     # Generated WAV/MP3 files go here.
```

The `local_voice/.gitignore` file keeps everything private except folder placeholders and the README.

Suggested first files you create manually:

```text
local_voice/reference/my-consented-reference.wav
local_voice/scripts/smoke-test.txt
local_voice/output/smoke-test.wav
```

Reference clip guidance:

- Use only your own voice or a voice you have explicit permission to clone.
- Start with 10 to 30 seconds of clean speech.
- Use WAV if possible, mono or stereo, 16 kHz or higher.
- Avoid music, noise, reverb, and overlapping speakers.

## Readiness Check

Run the local check script from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\local-voice\check-local-voice.ps1 -CreateFolders
```

What it does:

- Creates the local private folders when `-CreateFolders` is passed.
- Checks Windows, CPU, RAM, Python, uv, FFmpeg, Docker, and PowerShell.
- Checks whether Voicebox is reachable at `http://127.0.0.1:17493`.
- Checks whether a Chatterbox-compatible API is reachable at `http://127.0.0.1:4123/v1`.
- Does not download models.
- Does not generate audio.
- Does not read or upload voice samples.

## Smoke Test Plan

1. Prepare a reference voice clip.

   Put it in:

   ```text
   local_voice/reference/
   ```

   Keep it private and out of git.

2. Prepare short script text.

   Example:

   ```text
   This is a local narration smoke test for a short-form video workflow. The goal is clear speech, stable pacing, and an audio file that can be imported into MoneyPrinterTurbo.
   ```

   Save it as:

   ```text
   local_voice/scripts/smoke-test.txt
   ```

3. Generate a short output file.

   In Voicebox, create or select the voice profile, paste the script text, generate speech, and export:

   ```text
   local_voice/output/smoke-test.wav
   ```

   If using a Chatterbox API server instead, generate to:

   ```text
   local_voice/output/smoke-test.mp3
   ```

4. Manual MoneyPrinterTurbo step.

   Use MoneyPrinterTurbo normally to create a video draft. Then manually replace the generated narration audio with `local_voice/output/smoke-test.wav` or `local_voice/output/smoke-test.mp3` in your video editor, or copy it into the relevant task folder only for local experimentation.

5. Review before integrating.

   Check:

   - Voice similarity is acceptable and consented.
   - Audio has no hallucinated extra speech.
   - Timing is short enough for the target video.
   - Volume is consistent.
   - Subtitles still make sense after the audio swap.

## Model Download Policy

Do not let setup scripts download large models automatically.

Before downloading any voice model, document:

- Tool and model name.
- Official source, model license, and code license.
- Evidence that the reference speaker consented to this specific use.
- Expected download size.
- Expected disk cache location.
- Whether the tool retains history, profiles, or source audio and how to delete it.
- Whether CPU mode is supported.
- Whether the model is required for the first smoke test.

For this laptop, prefer a small engine first and test one short line before downloading larger multilingual or high-quality models.

## Decision Summary

Recommended first path: Voicebox.sh GUI/API.

Fallback path: Chatterbox API server, because MoneyPrinterTurbo already has a compatible Chatterbox client.

Defer: direct Qwen3-TTS until you have a stronger machine or a server wrapper that exposes an OpenAI-compatible speech endpoint.

## Next Integration Prompt

Use this after the local smoke test produces a good WAV/MP3:

```text
I have a local generated narration file at local_voice/output/smoke-test.wav. Inspect MoneyPrinterTurbo's task/audio pipeline and add the smallest safe workflow to use a pre-generated local narration file instead of calling TTS. Keep existing TTS behavior unchanged, protect against path traversal, do not commit audio files, and add tests for the new local-audio path.
```
