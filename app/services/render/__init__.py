"""Render backends.

`local` is the default and unchanged. `rendobar` is an opt-in cloud backend. The
dispatcher below picks the selected backend, checks it can serve the job, and
always falls back to Local on ineligibility or error so a render never fails just
because an optional backend had a problem.

Add your own backend: implement RenderBackend (see base.py) and register it in
BACKENDS.
"""

from loguru import logger

from app.services.render.base import RenderBackend, RenderContext
from app.services.render.local import LocalRenderBackend
from app.services.render.rendobar import RendobarRenderBackend, rendobar_eligible

BACKENDS = {
    "local": LocalRenderBackend,
    "rendobar": RendobarRenderBackend,
}

__all__ = [
    "RenderBackend",
    "RenderContext",
    "BACKENDS",
    "get_render_backend",
    "render_with_fallback",
]


def get_render_backend(name: str) -> RenderBackend:
    return BACKENDS.get(name or "local", LocalRenderBackend)()


def render_with_fallback(ctx: RenderContext) -> None:
    """Render with the selected backend, falling back to Local when needed."""
    name = (getattr(ctx.params, "render_backend", "local") or "local").lower()

    if name == "rendobar" and not rendobar_eligible(ctx.params):
        logger.warning(
            "Rendobar backend not eligible (no API key set). Using local render."
        )
        name = "local"

    if name == "local":
        LocalRenderBackend().render(ctx)
        return

    try:
        get_render_backend(name).render(ctx)
    except Exception as e:
        # Any backend failure must not break the run, fall back to local.
        logger.error(f"{name} render failed ({e}), falling back to local render")
        LocalRenderBackend().render(ctx)
