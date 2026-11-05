# Docker Config Note

Before starting the supplied Docker Compose services for the first time, copy `config.example.toml` to `config.toml` in the repository root:

```bash
cp config.example.toml config.toml
docker compose -f docker-compose.release.yml up
```

If `config.toml` already exists as a regular file, keep it rather than overwriting your settings. The supplied Compose files bind-mount this host file into the containers. If it is missing, Compose can create a directory at that path, preventing the application from loading or initializing its configuration.

Create the file before startup even if you plan to enter API keys later in the WebUI. Once the WebUI starts, add cloud LLM, media, or video-service credentials from its basic settings.

Application-level automatic creation from `config.example.toml` is available in deployment modes without a missing-file bind mount obstructing initialization; it does not replace this prerequisite for the supplied Compose deployment.
