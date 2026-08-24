MoneyPrinterTurbo macOS setup and English WebUI change plan

1. Verify the local repository state and read the project setup documentation.
2. Install only the documented non-Docker local runtime requirements on macOS:
   uv, Python 3.11, and the locked Python dependencies.
3. Confirm the local application can import its configuration and resolve FFmpeg
   through the project environment.
4. Start and inspect the Streamlit WebUI locally.
5. Make the WebUI open in English by default for fresh sessions while preserving
   the existing language selector for explicit user choices.
6. Translate remaining hard-coded WebUI/public-facing Chinese strings to English
   without changing video generation behavior or business logic.
7. Run focused tests for WebUI startup and internationalization.
8. Commit the setup and English WebUI translation changes to the fork.
