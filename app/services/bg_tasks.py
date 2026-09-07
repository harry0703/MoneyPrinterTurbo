# Module-level task registry for background video generation.
# Lives in an imported module (not Main.py) so it survives Streamlit script
# reruns, which re-execute Main.py but do NOT re-import already-loaded modules.
#
# Schema per task_id:
#   {"result": Any, "error": str|None, "done": bool}

_TASKS: dict = {}
