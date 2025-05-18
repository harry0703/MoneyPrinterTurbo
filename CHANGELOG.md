README Updates: The Chinese README (README.md) was heavily revised to include more English content and better structure, while the English README (README-en.md) 
was removed entirely. Much of the documentation, quick start, and FAQs are now unified in a single README and available in English.
CHANGELOG.md Added: A new changelog file was created to track updates and features.
Video Processing Improvements (app/services/video.py):
Enhanced the video combining and processing logic by introducing more ffmpeg parameters for improved video encoding (e.g., preset, CRF, pixel format settings).
Improved resizing methods (using 'lanczos') for better video quality.
Updated functions to better handle merging, audio, and encoding parameters for output files.
Added more robust logic for video preprocessing, merging, and clip writing, with commented-out code for optional features.
Windows Web UI Startup Script (webui.bat):
Improved the script to automatically activate a Python virtual environment if present.
Clarified optional Hugging Face mirror settings.
Overall, this commit modernizes the documentation, improves video encoding quality and flexibility, and makes the Windows startup script more robust and user-friendly.
