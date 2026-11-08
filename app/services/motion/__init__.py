"""Motion Studio: storyboard-driven motion-graphics Shorts with an animated host.

Pipeline: writer (LLM storyboard) -> speech (Edge TTS per beat) -> renderer (Chrome frames into
ffmpeg). jobs.py runs it in the background for the /api/v1/motion routes.
"""
