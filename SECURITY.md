# Security Policy

## Safe Deployment Defaults

- Keep API and WebUI access on localhost or behind a trusted authenticated reverse proxy.
- Set `app.api_key` before using any `/api/v1/*` endpoint.
- Do not expose the Streamlit WebUI to untrusted users until it has external authentication.
- Keep provider API keys out of screenshots, logs, bug reports, and shared config files.
- Rotate any provider key that was entered into an exposed or shared WebUI.

## Upload And Media Handling

- Local BGM and video-material uploads are size-limited by `app.max_upload_file_size_mb`.
- Uploaded and externally downloaded media still passes through native media parsers. Treat untrusted media as high risk and run production workloads in an isolated container or worker.

## Dependency Hygiene

- Prefer `uv sync` from `uv.lock`.
- Run `pip-audit` or an equivalent dependency scanner before deployment.
- The optional unofficial `g4f` provider is not installed by the legacy `requirements.txt` path by default.
- Current `moviepy==2.1.2` constrains `Pillow` below the patched `12.x` line. Treat image/font/PDF/PSD parsing as untrusted and isolated until MoviePy supports a fixed Pillow version or the media pipeline is refactored.

## Reporting

Please report suspected security issues through GitHub issues only if no secrets or exploit details are included. For sensitive details, contact the maintainer privately first.
