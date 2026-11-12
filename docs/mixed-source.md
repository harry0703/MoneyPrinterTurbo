# Mixed source: Pixabay + AI-generated images

Stock footage is free but generic; a dedicated image API (configured through
`openai_image_*`, e.g. Google Gemini) can match the script closely but costs
money per image. `video_source = "mixed"` picks one or the other **per
script term**, so a single video can use both.

## Enabling it

1. Configure `openai_image_base_url` and `openai_image_model` as you would
   for the plain `"openai_image"` source (see the main README and
   `config.example.toml`). `mixed` reuses that same endpoint for its
   generated half.
2. Set `video_source = "mixed"` in `config.toml`, or pick **"Mixed Pixabay
   and AI Images"** from the WebUI's video source dropdown.
3. Configure the mix in `config.toml` (or the WebUI's material settings
   dialog, under the same tab as the OpenAI image settings):

```toml
[app]
video_source = "mixed"
mixed_source_pixabay_weight = 0.5   # 0.0 = all Pixabay, 1.0 = all generated
mixed_source_strategy = "ratio"     # "ratio" | "alternate" | "prompt_based"
```

A request made through the API or CLI can override both per call with the
`source_mix_ratio` (float, 0.0-1.0) and `source_mix_strategy` fields on
`VideoParams`; the `config.toml` values above are only the default used when
a request omits them.

## Strategies

- **`ratio`** (default): spreads `mixed_source_pixabay_weight` evenly across
  the script's terms instead of bunching the generated images at the start,
  so later scenes get a fair share too.
- **`alternate`**: alternates API, Pixabay, API, Pixabay, ... term by term,
  ignoring the ratio.
- **`prompt_based`**: a small keyword heuristic. Terms that look abstract
  (e.g. "freedom", "progress", "legacy") go to the image API; terms that
  look concrete/physical (e.g. "shipyard", "tank", "coast") go to Pixabay.
  A term matching neither list falls back to alternating, so a whole script
  never ends up on a single source just because none of its terms matched
  the lists.

## Cost and safety

Exactly one Pixabay search or one paid image generation happens per term,
in the script's term order, stopping as soon as the accumulated clip
duration covers the narration — the same "generate on demand, stop once
covered" rule the plain `openai_image` source already follows. Turning on
`match_materials_to_script` is not required, but is recommended: it is what
makes those terms follow the narrative order in the first place, so mixing
two sources still reads as one coherent sequence instead of two interleaved
random ones.

## Limits

- Combining this with `match_materials_to_script` still generates exactly 8
  terms (the hard-coded amount `app/services/llm.py` requests), so very long
  videos still reuse/repeat clips once the narration outlasts
  `8 * video_clip_duration` seconds — the same limit the plain
  `openai_image` source has.
- The term-generation prompt itself (in `app/services/llm.py`) is not aware
  of the mixed strategy; it only ever produces plain stock-style search
  terms. `prompt_based` routes those terms by English keyword matching, it
  does not rewrite them.
