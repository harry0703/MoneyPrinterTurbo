# Displaying media

Use the typed media command for images, video, audio, and PDFs — each renders a proper viewer/player with the right controls. Don't embed media with raw HTML (`unsafe_allow_html`) or an `st.components` iframe hack; the native commands handle formats, sizing, and theming.

## Accessible names (`alt`)

Pass keyword-only `alt=` so assistive technologies can name the media. Write a short, plain-text name appropriate to the media (about one sentence). Do not open with "Image of…"; do not paste the same string into `caption` and `alt`.

- **`st.image` / `st.pyplot`:** `alt` is independent of `caption`. Use `alt=""` only for decorative images. Omitting `alt` leaves the image without an accessible name. For multiple images, pass a same-length sequence with one alt value per image (use ``None`` to skip one); a single string raises an exception.
- **`st.video` / `st.audio`:** `alt` names the player. For video captions (WCAG 1.2.2), use `subtitles=`, not `alt`.
- **`st.pdf`:** `alt` names the viewer, not the PDF's page content.
- **`st.iframe`:** `alt` sets the iframe `title`. Omit it only when the default title (`"st.iframe"` on every embed) is acceptable.

A whitespace-only `alt` is ignored (same as not passing `alt`) and logged on every command. Empty `alt=""` is decorative only on `st.image` / `st.pyplot`.

## Images: st.image

```python
st.image(
    "chart.png",
    caption="Q3 revenue",
    alt="Bar chart of monthly Q3 revenue rising to $1.2M in September",
    width="stretch",
)
```

Accepts a file path, URL, `PIL.Image`, NumPy array, or bytes. `st.pyplot` takes the same keyword-only `alt` (including decorative `""`).

- Width: `width="content"` (default) sizes to the content; `width="stretch"` fills the container; `width=<pixels>` is a fixed size. Do not use deprecated `use_container_width` (`True` → `"stretch"`; `False` → `"content"` unless `width` is an integer, in which case keep that width).

## Video: st.video

```python
st.video("clip.mp4", alt="Product walkthrough, 3 minutes")
st.video("https://youtu.be/<id>", alt="Conference keynote recording")
st.video("clip.mp4", subtitles="captions.vtt", alt="Onboarding demo with captions")
```

Accepts a path, URL, or bytes. Supports `start_time` / `end_time`, `autoplay`, `muted`, `loop`, and subtitles.

## Audio: st.audio

```python
st.audio("track.mp3", alt="Q2 earnings call recording")
st.audio(samples, sample_rate=44100, alt="Synthesized tone sample")
```

Accepts a path, URL, bytes, or a NumPy sample array (with `sample_rate`). Supports `start_time`, `autoplay`, and `loop`.

## PDFs: st.pdf

**`st.pdf` needs an extra dependency.** It is not available in a bare Streamlit install:

```shell
pip install streamlit[pdf]
```

```python
st.pdf("report.pdf", height=600, alt="Q3 2026 financial report")
```

Renders a PDF inline from a path, URL, bytes, or file-like object (`height` defaults to 500). Prefer it over an `st.components` HTML `<iframe>`/`<embed>` hack for showing a PDF — but add the extra to the app's dependencies, or the app fails at runtime.

## Logo: st.logo

`st.logo` pins a brand image to the top of the sidebar/header — distinct from `st.image`, which places an image in the page's content flow. See [design.md](design.md). It has no `alt` parameter because Streamlit treats the logo as app chrome, not page content.

## References

- [st.image](https://docs.streamlit.io/develop/api-reference/media/st.image)
- [st.video](https://docs.streamlit.io/develop/api-reference/media/st.video)
- [st.audio](https://docs.streamlit.io/develop/api-reference/media/st.audio)
- [st.pdf](https://docs.streamlit.io/develop/api-reference/media/st.pdf)
- [st.logo](https://docs.streamlit.io/develop/api-reference/media/st.logo)
