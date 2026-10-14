# Docker Config Note

The Docker quick start can use the generated `config.toml` path.

On first launch, MoneyPrinterTurbo creates `config.toml` from `config.example.toml`. You only need to create `config.toml` manually when you want to pre-fill API keys or other settings before starting the containers.

```bash
docker compose -f docker-compose.release.yml up
```

After the WebUI starts, add cloud LLM, media, or video-service credentials from the WebUI basic settings.
