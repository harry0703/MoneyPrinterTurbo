# Security Review — MoneyPrinterTurbo

**Date:** 2026-05-31
**Scope:** Static review of the local repo (branch `main`, HEAD `8b2e530`). Source-level analysis; no dynamic testing or dependency CVE scan was run.

> **Remediation status (2026-05-31):** Findings #1–#7 have been fixed in the working tree (see "Remediation applied" at the end). The findings below are kept as the original audit record.

## Summary

The codebase shows real, recent security hardening: path-traversal protection (`app/utils/file_security.py`), upload filename sanitization, TLS verification on by default, and the risky `g4f` provider disabled by default. Those are good.

The dominant remaining problem is that **the FastAPI API ships with all authentication disabled**, while the server defaults to binding every network interface. That single gap turns several otherwise-acceptable endpoints (file upload, file download/stream, task deletion, paid LLM calls) into things any host on the network can drive. Most of what follows flows from that.

| # | Severity | Issue |
|---|----------|-------|
| 1 | High | API authentication disabled on all routes |
| 2 | Medium | Server binds `0.0.0.0` by default |
| 3 | Medium | `/tasks` static mount uses `follow_symlink=True`, bypassing path checks |
| 4 | Medium | CORS allows all origins with credentials |
| 5 | Low/Med | Dockerfile: `chmod 777` on app dir, runs as root |
| 6 | Low | Unbounded in-memory file uploads (DoS) |
| 7 | Low | Unhandled `Range` header parsing in stream endpoint |
| 8 | Info | `tls_verify=false` escape hatch; g4f supply-chain risk |

---

## Findings

### 1. API authentication is disabled on every route — High

`app/controllers/v1/video.py:37` and `app/controllers/v1/llm.py:14` both have the auth dependency commented out:

```python
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()
```

A complete `verify_token` implementation exists in `app/controllers/base.py` but is never wired in. As shipped, **every** endpoint is unauthenticated, including:

- `POST /api/v1/videos`, `/subtitle`, `/audio` and `POST /api/v1/scripts`, `/terms` — trigger work that spends the operator's **paid Pexels/Pixabay and LLM API keys**.
- `POST /api/v1/musics`, `/video_materials` — upload files to the server.
- `GET /api/v1/download/{path}`, `/stream/{path}` — read generated files.
- `DELETE /api/v1/tasks/{task_id}` — delete tasks and their output directories (`shutil.rmtree`).

Anyone who can reach the port can run up API bills, fill disk, and delete data.

Also note that even when enabled, `verify_token` compares tokens with `!=` (`base.py`), which is not constant-time, and an empty configured `api_key` would accept an empty token. Use `secrets.compare_digest` and reject empty keys.

**Fix:** uncomment the dependency on both routers, require a non-empty `api_key`, and use a constant-time comparison.

### 2. Server binds `0.0.0.0` by default — Medium

`app/config/config.py:175`:

```python
listen_host = _cfg.get("listen_host", "0.0.0.0")
```

Combined with finding #1, the unauthenticated API is exposed on all interfaces — the LAN, and the public internet if the host is reachable. Default to `127.0.0.1` and require an explicit opt-in to bind externally.

### 3. `/tasks` static mount follows symlinks — Medium

`app/asgi.py`:

```python
app.mount("/tasks", StaticFiles(directory=task_dir, html=True, follow_symlink=True), name="")
```

The careful `file_security.resolve_path_within_directory` checks guard the `/download` and `/stream` handlers, but this static mount serves the task directory directly and **bypasses them**. `follow_symlink=True` means any symlink that ends up inside `storage/tasks` resolves outside the directory, exposing arbitrary host files over the (unauthenticated) HTTP server. Drop `follow_symlink=True` unless there's a concrete need, and keep file serving behind the validated handlers.

### 4. CORS allows all origins with credentials — Medium

`app/asgi.py`:

```python
origins = cors_allowed_origins_str.split(",") if cors_allowed_origins_str else ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
```

`allow_origins=["*"]` with `allow_credentials=True` is an invalid/permissive combination (browsers reject the wildcard when credentials are sent, but the intent is wrong and breaks the moment a specific origin is configured). Set a concrete allow-list via `CORS_ALLOWED_ORIGINS` and don't default to `*`.

### 5. Dockerfile runs as root with a world-writable app directory — Low/Medium

`Dockerfile`:

```dockerfile
RUN chmod 777 /MoneyPrinterTurbo
```

No `USER` directive, so the container runs as root, and the entire app directory is world-writable (`777`) — any process in the container can overwrite application code. It also relaxes the ImageMagick policy (`sed -i '/<policy domain="path".../d'`), widening what ImageMagick will process. Add a non-root `USER`, use tighter permissions (`755`), and keep the ImageMagick path policy unless a specific feature needs it.

### 6. Unbounded in-memory uploads — Low

`upload_bgm_file` / `upload_video_material_file` (`video.py`) do `buffer.write(file.file.read())` — the whole upload is read into memory with no size cap. Unauthenticated (see #1), this is an easy memory/disk exhaustion vector. Enforce a max content length and stream to disk in chunks. (Extension is validated and the filename is sanitized — those parts are fine.)

### 7. Unhandled `Range` parsing in `/stream` — Low

`stream_video` parses the client `Range` header with `int(part)` and no try/except. A malformed header (`Range: bytes=abc-`) raises and returns a 500; crafted values can produce odd seeks/lengths. Validate and clamp `start`/`end` against `video_size` and return `416` on invalid ranges.

### 8. Informational

- `material.py` supports `tls_verify=false`, which disables certificate validation for API calls and downloads. It defaults to `true` and logs a warning — acceptable, but document that it must stay on outside trusted proxies.
- The `g4f` provider relies on reverse-engineered third-party endpoints (supply-chain/legal risk). It's correctly disabled by default and gated behind `enable_g4f=true` — good.
- No secrets are committed; `config.toml` is git-ignored and `config.example.toml` ships empty keys. Good.
- `state.py` uses `ast.literal_eval` (safe), and the ffmpeg call in `video.py` uses an argument list (no `shell=True`) on server-controlled paths — both fine.

---

## Recommended priority

1. Re-enable `verify_token` on both routers; require a non-empty key and constant-time compare (#1).
2. Default `listen_host` to `127.0.0.1` (#2).
3. Remove `follow_symlink=True` from the `/tasks` mount (#3).
4. Tighten CORS defaults (#4).
5. Harden the Dockerfile and add upload size limits (#5, #6).

Items 1–2 together close the largest exposure and are small changes.

---

## Remediation applied (2026-05-31)

All findings except #8 (informational) were fixed:

- **#1 — Auth enabled.** `app/controllers/base.py:verify_token` now fails closed (rejects all requests when no `api_key` is configured) and uses `secrets.compare_digest` for a constant-time comparison. The dependency is wired into both routers (`app/controllers/v1/video.py`, `app/controllers/v1/llm.py`). Verified with a functional test covering no-key/correct/wrong/missing-header cases.
- **#2 — Binding.** `listen_host` now defaults to `127.0.0.1` (`app/config/config.py`).
- **#3 — Symlinks.** `follow_symlink=True` removed from the `/tasks` static mount (`app/asgi.py`).
- **#4 — CORS.** No longer defaults to `*`; uses concrete localhost origins unless `CORS_ALLOWED_ORIGINS` is set (`app/asgi.py`).
- **#5 — Docker.** `chmod 777` removed; image now creates and runs as non-root `appuser` (UID 1000) with `COPY --chown` (`Dockerfile`).
- **#6 — Uploads.** Both upload endpoints stream to disk with a configurable cap (`max_upload_size_mb`, default 512) and return 413 on oversize (`app/controllers/v1/video.py`).
- **#7 — Range.** `/stream` parses the `Range` header defensively, clamps bounds, and returns 416 on malformed input. Verified with 10 parsing test cases.

### Action required by you

To use the **HTTP API** (port 8080), set a strong key in `config.toml` and send it as the `x-api-key` header:

```toml
[app]
api_key = "<paste output of: python -c 'import secrets; print(secrets.token_urlsafe(32))'>"
```

```bash
curl -H "x-api-key: YOUR_KEY" http://127.0.0.1:8080/api/v1/musics
```

The **Streamlit WebUI** (port 8501) is unaffected — it calls the services directly, not the HTTP API. To deliberately expose the API beyond localhost, set `listen_host = "0.0.0.0"` *and* keep `api_key` set, ideally behind a reverse proxy with TLS.
