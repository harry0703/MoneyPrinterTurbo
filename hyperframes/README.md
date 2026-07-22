# MoneyPrinterTurbo HyperFrames template

Shared template for optional HyperFrames rendering
(https://github.com/heygen-com/hyperframes).

When `video_renderer = "hyperframes"` in `config.toml`, each output video gets a
standalone project under:

```text
storage/tasks/<task_id>/hyperframes-<index>/
```

That project includes this HTML composition, staged media in `assets/`, and can
be previewed or re-rendered:

```bash
cd storage/tasks/<task_id>/hyperframes-<index>
npx hyperframes preview
npx hyperframes render --output out.mp4 --quality standard --fps 30
```

## Setup (once)

1. Install [Node.js 22+](https://nodejs.org/)
2. Install [FFmpeg](https://ffmpeg.org/)
3. Run:

```bash
npx hyperframes browser ensure
npx hyperframes doctor
```

4. Set `video_renderer = "hyperframes"` in `config.toml`, or choose HyperFrames
   under **Video Renderer** in the WebUI.
