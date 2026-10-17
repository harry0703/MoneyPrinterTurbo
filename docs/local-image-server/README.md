# Local image server for `openai_image`

Stock footage often has little to do with the script. The `openai_image` source fixes that by generating one image per script segment. This folder has a small server that does it on your own GPU, so there are no per-image costs.

It exposes the OpenAI `/v1/images/generations` API and runs [RealVisXL V5.0 Lightning](https://huggingface.co/SG161222/RealVisXL_V5.0_Lightning), a photoreal SDXL model that needs about 6 steps per image.

Tested on an RTX 5070 Ti (16 GB):

- about 2.3 s per 832x1216 image
- about 7 minutes for a 50 s video with 8 scenes, including voice, Whisper subtitles and rendering

## Setup

```bash
cd docs/local-image-server
python -m venv .venv
.venv/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cu128
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python server.py
```

To run the policy tests from the repo root: `python -m pytest test/services/test_local_image_policy.py` (stdlib only, no GPU needed).

The first request downloads the fp16 weights, about 6.6 GB. The server listens on `http://127.0.0.1:7861`.

## config.toml

```toml
[app]
video_source = "openai_image"
openai_image_base_url = "http://127.0.0.1:7861/v1"
openai_image_model = "realvisxl-v5-lightning"
match_materials_to_script = true
video_clip_duration = 6
```

`match_materials_to_script` asks the LLM for up to 8 keywords in narration order, which gives one scene per part of the script. Each image becomes one clip, so 8 keywords x 6 s covers about 48 s of narration. With shorter clips, scenes repeat to fill the gap.

## Sharing the GPU with Ollama

SDXL needs about 8 GB of VRAM, so a 14B Ollama model and SDXL don't fit on a 16 GB card together. Before generating, the server unloads any running Ollama model. After `IMAGE_IDLE_SECONDS` (90 by default) without a request, it moves SDXL back to the CPU. Ollama then loads normally for the next script.

## Options

| Variable | Default | |
|---|---|---|
| `IMAGE_MODEL` | `SG161222/RealVisXL_V5.0_Lightning` | any SDXL repo with fp16 weights |
| `IMAGE_STEPS` | `6` | |
| `IMAGE_GUIDANCE` | `1.5` | |
| `IMAGE_IDLE_SECONDS` | `90` | |
| `IMAGE_PORT` | `7861` | |
| `OLLAMA_URL` | `http://localhost:11434` | |
| `CONTENT_POLICY` | `policy.toml` | path to a policy file, or `off` |

## Content policy

Scene keywords come from an LLM, so a video about religion or history can ask the image model for things that shouldn't be generated. Before each prompt reaches the model, `policy.toml` checks it. The policy is on by default, and a rule only acts when its keywords appear.

| Rule | What it does |
|---|---|
| `god` | God is never shown as a figure. The scene becomes light breaking through clouds. |
| `prophet_muhammad`, `islamic_prophets`, `companions_and_family_of_the_prophet` | No depiction, following Islamic practice. The scene becomes an empty landscape of the place mentioned (Mecca, Medina, Hira, Sinai, Jerusalem), or a desert at sunrise otherwise. |
| `bahai_central_figures`, `sikh_gurus` | No depiction. The scene becomes a fitting place without people. |
| `atrocities` | No fabricated "historical photos" of real atrocities. The scene becomes a candle memorial. |
| `children_in_distress` | The scene becomes a symbolic image without people. |
| `living_public_figures` | No photoreal faces of named office holders. The scene becomes a government building. |
| `sacred_script` | Image models write fake Arabic, Hebrew, Sanskrit or Gurmukhi, so calligraphy becomes geometric patterns. |
| `holy_books` | Holy books are shown closed, with no lettering. |
| `revered_figures` | Jesus, Mary, the Buddha, Hindu deities and others are depicted in these traditions, so they're kept, framed reverently. |

`islamic_prophets_english_names` is off by default. For Islamic content, switch it on so Jesus, Moses, Abraham and Noah are also shown as places rather than people.

Swapping in a whole scene is deliberate. A negative prompt alone doesn't keep people out reliably: in testing it still produced figures in 2 of 6 prophet scenes. Raising the guidance strength to compensate burned the Lightning model's images.

Known limits: keyword rules miss phrasings they don't list and can misfire on common names (Muhammad Ali, a person called Isa). `test/services/test_local_image_policy.py` covers the expected cases. Edit `policy.toml` to fit your audience.
