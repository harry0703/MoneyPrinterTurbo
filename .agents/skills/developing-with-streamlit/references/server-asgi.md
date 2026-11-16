# Advanced server configuration with st.App

Use `st.App` when a normal Streamlit script needs ASGI-level composition: custom HTTP routes, middleware, startup/shutdown hooks, programmatic secrets, custom exception handling, or mounting with another ASGI framework.

Do not create an ASGI wrapper for a simple app that only needs Streamlit UI and ordinary Streamlit configuration. When the app does need advanced server features, keep the UI in a normal Streamlit script and launch the `st.App` wrapper with `streamlit run asgi_app.py` when possible.

## Contents

- [When to use it](#when-to-use-it)
- [Basic ASGI wrapper](#basic-asgi-wrapper)
- [Direct Python launchers with App.run()](#direct-python-launchers-with-apprun)
- [Script paths](#script-paths)
- [Custom routes](#custom-routes)
- [Middleware](#middleware)
- [Lifespan hooks](#lifespan-hooks)
- [Mount another ASGI app inside Streamlit](#mount-another-asgi-app-inside-streamlit)
- [Mount Streamlit inside FastAPI](#mount-streamlit-inside-fastapi)
- [Programmatic secrets](#programmatic-secrets)
- [Error handling](#error-handling)
- [Limitations and cautions](#limitations-and-cautions)
- [References](#references)

## When to use it

Use `st.App` for:
- Custom REST or webhook endpoints alongside a Streamlit app
- HTTP middleware for security headers, request logging, authentication, or CORS
- Startup/shutdown work through ASGI lifespan hooks
- Mounting FastAPI, Starlette, or another ASGI app beside Streamlit
- Mounting Streamlit inside a parent ASGI app
- Programmatically supplying secrets to `st.secrets`
- Custom script-error or network exception handling

Do not use it just to set ports, headless mode, theme options, or regular Streamlit config. Use `.streamlit/config.toml` or `streamlit run` flags for those.

## Basic ASGI wrapper

Keep the Streamlit UI in a normal script, then create a separate ASGI wrapper.

```python
# streamlit_app.py
import streamlit as st

st.title("Dashboard")
st.write("This is the normal Streamlit script.")
```

```python
# asgi_app.py
import streamlit as st

app = st.App("streamlit_app.py")
```

Run with Streamlit's CLI when possible:

```bash
streamlit run asgi_app.py
```

`streamlit run` detects the ASGI app instance and runs it with Streamlit's uvicorn integration. You can also run it with an ASGI server directly:

```bash
uvicorn asgi_app:app --host 0.0.0.0 --port 8501
```

`st.App` is the official import path for the ASGI entry point.

## Direct Python launchers with `App.run()`

For shareable ASGI launchers that should run with `python app.py`, `uv run app.py`,
or `uvx --with streamlit python app.py`, call `App.run()` under a main guard in
the wrapper:

```python
# app.py
import streamlit as st

app = st.App("streamlit_app.py")

if __name__ == "__main__":
    app.run()
```

Use `app.run(config={...})` for programmatic config overrides that would otherwise be
passed as `streamlit run` flags:

```python
if __name__ == "__main__":
    app.run(config={"server.port": 8502, "server.address": "0.0.0.0"})
```

This pairs well with inline script dependencies when launched with `uv run app.py`:
the wrapper can declare `streamlit` and any launcher-only dependencies in a PEP 723
`script` metadata block at the top of the file.

```python
# /// script
# dependencies = [
#   "streamlit",
# ]
# ///

import streamlit as st

app = st.App("streamlit_app.py")

if __name__ == "__main__":
    app.run()
```

Use this pattern only for launcher modules such as `app = st.App("streamlit_app.py")`.
Avoid same-file launchers like `app = st.App(__file__)`: Streamlit executes app scripts
in a fake `__main__` module, so an `if __name__ == "__main__": app.run()` block inside
the Streamlit script can run again during app execution.

## Script paths

The `script_path` argument points to the Streamlit UI script, not the ASGI wrapper.

Relative paths are resolved differently depending on how the app starts:
- With `streamlit run asgi_app.py`, relative paths resolve from the script passed to `streamlit run`.
- With `App.run()` direct launchers (`python asgi_app.py`, `uv run asgi_app.py`,
  or `uvx --with streamlit python asgi_app.py`), relative paths resolve from the
  launcher module.
- With `uvicorn asgi_app:app`, relative paths resolve from the current working directory.

Use an absolute path if the wrapper may be imported from different working directories.

## Custom routes

Add Starlette routes when the app needs lightweight API endpoints.

```python
import streamlit as st
from starlette.responses import JSONResponse
from starlette.routing import Route


async def health(request):
    return JSONResponse({"status": "ok"})


async def data(request):
    return JSONResponse({"items": ["apple", "banana", "cherry"]})


app = st.App(
    "streamlit_app.py",
    routes=[
        Route("/api/health", health),
        Route("/api/data", data),
    ],
)
```

User routes are added before Streamlit's internal routes, but they cannot conflict with reserved Streamlit route prefixes:
- `/_stcore/`
- `/media/`
- `/component/`
- `/static/`

Prefer namespaced routes such as `/api/...` or `/webhook/...`.

## Middleware

Add Starlette middleware for request/response behavior around the whole app.

```python
import streamlit as st
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response


app = st.App(
    "streamlit_app.py",
    middleware=[Middleware(SecurityHeadersMiddleware)],
)
```

User middleware runs before Streamlit's internal middleware on requests and after it on responses.

## Lifespan hooks

Use lifespan hooks for process-level startup/shutdown work, not per-user session state. A common pattern is to preload shared cached resources or data before the first browser session connects.

```python
# resources.py
import streamlit as st


@st.cache_resource
def get_database():
    return connect_to_database()


@st.cache_data
def load_reference_data():
    return fetch_reference_data()
```

```python
# asgi_app.py
from contextlib import asynccontextmanager

import streamlit as st


@asynccontextmanager
async def lifespan(app):
    # Import cached functions after st.App has started the Streamlit runtime.
    from resources import get_database, load_reference_data

    print("Starting Streamlit ASGI app...")
    get_database()  # Warm st.cache_resource.
    load_reference_data()  # Warm st.cache_data.
    yield {"ready": True}
    print("Shutting down Streamlit ASGI app...")


app = st.App("streamlit_app.py", lifespan=lifespan)
```

Put cached functions in a shared module when both the Streamlit script and the ASGI wrapper need to call them. For per-user state inside the Streamlit script, use `st.session_state`.

Import and call cached functions inside the lifespan hook rather than at launcher module
scope. The launcher module is imported before Streamlit starts its runtime, so a module-scope
`@st.cache_data` decoration is validated against a temporary in-memory storage manager and
logs a `No runtime found` warning (`@st.cache_resource` doesn't use that decoration-time
path). Either way, the real cache storage is only selected when a cached function is first
called, so warming inside the lifespan—after the runtime has started—uses the real cache and
avoids the warning.

If ASGI routes or middleware need process-level state that is not a Streamlit resource, the lifespan context manager may yield a dictionary. Those values are stored on `app.state` (`app.state["ready"]` in the example above).

### Scheduled background refresh for specific keys

`refresh_mode="background"` is the simplest way to avoid blocking on expiration when
slightly stale data is acceptable. It is access-driven, however: refresh starts only when a
call observes an expired entry, and that call receives the stale value.

For advanced cases that need the server to initiate refreshes even without user traffic, use
a lifespan task to periodically call the cached function with the arguments for each key that
should stay warm. Calls made while an entry is fresh are cheap cache hits. The first scheduled
call after its `ttl` returns the stale value to the task and triggers a deduplicated background
refresh for that specific key. Run synchronous cached functions in a worker thread (via
`anyio`, already a Streamlit dependency) so they don't block the ASGI event loop.

```python
# resources.py
import streamlit as st


@st.cache_data(ttl="10m", refresh_mode="background")
def load_metrics(dataset):
    return fetch_metrics(dataset)
```

```python
# asgi_app.py
import logging
from contextlib import asynccontextmanager

import anyio
import streamlit as st

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    # The Streamlit runtime is available when the user lifespan starts.
    from resources import load_metrics

    async def touch_periodically():
        while True:
            await anyio.sleep(60)
            try:
                # Only touch the cache entry for load_metrics("dashboard").
                await anyio.to_thread.run_sync(load_metrics, "dashboard")
            except Exception:
                logger.exception("Scheduled cache refresh failed")

    # Warm this specific key before serving requests. Unlike the periodic loop,
    # this initial warm isn't wrapped in try/except, so a failure aborts startup.
    await anyio.to_thread.run_sync(load_metrics, "dashboard")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(touch_periodically)
        try:
            yield
        finally:
            task_group.cancel_scope.cancel()


app = st.App("streamlit_app.py", lifespan=lifespan)
```

This pattern works for global `st.cache_data` and `st.cache_resource` entries whose argument
combinations are known to the scheduler. Each argument combination is a separate cache key,
so touching `load_metrics("dashboard")` does not refresh or invalidate entries for other
datasets.

Keep these caveats in mind:

- **This does not refresh before the TTL.** Calls made while the entry is fresh return the
  current value without executing the cached function. Polling controls how soon the server
  notices expiration and triggers background refresh.
- **Poll comfortably below the stale window.** By default, background refresh serves the
  stale value for one extra `ttl`; past `2 × ttl` the entry is hard-evicted and the next
  call (including a scheduled touch) blocks on a foreground recompute. The
  `runner.cacheBackgroundRefreshTTLMultiplier` option changes that bound to `M × ttl`.
  Keep the polling interval well under `(M - 1) × ttl` so several touches land in the
  stale grace window. With the default `M = 2.0` that is well under `ttl`; with
  `M = 1.5`, poll comfortably below `0.5 × ttl` — a `0.75 × ttl` cadence can jump from
  fresh to hard expiry without triggering a background refresh.
- **Stale values remain possible.** The scheduled touch preserves the last good value while
  refreshing, but users can receive it until the refresh completes. If uninterrupted,
  atomically replaced fresh reads are required, refresh a shared external store instead.
- **Each worker warms independently.** Lifespan tasks run once per ASGI process, so a
  multi-worker deployment runs and warms every process on its own schedule.

## Mount another ASGI app inside Streamlit

Use `Mount` when Streamlit should own the root URL and another ASGI app should live under a subpath.

```python
import streamlit as st
from fastapi import FastAPI
from starlette.routing import Mount

api = FastAPI()


@api.get("/health")
async def health():
    return {"status": "ok"}


app = st.App(
    "streamlit_app.py",
    routes=[Mount("/api", app=api)],
)
```

With this structure, the Streamlit app is served at `/` and the FastAPI routes are served under `/api`.

## Mount Streamlit inside FastAPI

When a parent ASGI framework owns the root app, pass Streamlit's lifespan to the parent so the Streamlit runtime starts and stops correctly.

```python
import streamlit as st
from fastapi import FastAPI

streamlit_app = st.App("streamlit_app.py")
api = FastAPI(lifespan=streamlit_app.lifespan())


@api.get("/api/data")
async def get_data():
    return {"data": [1, 2, 3]}


api.mount("/dashboard", streamlit_app)
```

Run the parent app with an ASGI server:

```bash
uvicorn asgi_app:api --host 0.0.0.0 --port 8501
```

Only call `streamlit_app.lifespan()` when a parent ASGI framework will manage the lifecycle. Do not call `lifespan()` and then serve that same `App` standalone.

## Programmatic secrets

Use `secrets=` to programmatically supply values that the Streamlit script should read through `st.secrets`.

```python
import os

import streamlit as st

app = st.App(
    "streamlit_app.py",
    secrets={
        "database": {
            "host": os.environ["DB_HOST"],
            "password": os.environ["DB_PASSWORD"],
        }
    },
)
```

Programmatic secrets are shallow-merged with file-based secrets, and programmatic values win at the top level.

## Error handling

Use `exception_handlers` for ASGI/network-layer exceptions from custom routes.

```python
import streamlit as st
from starlette.responses import JSONResponse
from starlette.routing import Route


class ApiError(Exception):
    pass


async def route_that_fails(request):
    raise ApiError("bad request")


async def api_error_handler(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=400)


app = st.App(
    "streamlit_app.py",
    routes=[Route("/api/fail", route_that_fails)],
    exception_handlers={ApiError: api_error_handler},
)
```

Use `on_script_error` for uncaught exceptions from the Streamlit script or widget callbacks.

```python
import streamlit as st


def handle_script_error(exc):
    st.error("Something went wrong.")
    return True  # Suppress the default exception display.


app = st.App("streamlit_app.py", on_script_error=handle_script_error)
```

Return `True` from `on_script_error` only when the handler shows its own user-facing error UI. Return `False` or `None` to let Streamlit show the normal exception display.

## Limitations and cautions

- Hosting multiple `App` instances with different `script_path` values in the same process is not supported.
- Lifespan hooks run once per process, not once per browser session.
- Custom routes and middleware run in the ASGI server context; Streamlit widget APIs belong in the Streamlit script.

## References

- [Starlette documentation](https://www.starlette.io/)
- [Uvicorn documentation](https://www.uvicorn.org/)
- [st.App](https://docs.streamlit.io/develop/api-reference/server/st.app)
