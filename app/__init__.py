from app.config.config import (
    app,
    whisper,
    proxy,
    azure,
    siliconflow,
    coze,
    ui,
    log_level,
    listen_host,
    listen_port,
    project_name,
    project_description,
    project_version,
    reload_debug,
    save_config,
)

# Create config object for easy access
class Config:
    def __init__(self):
        self.app = app
        self.whisper = whisper
        self.proxy = proxy
        self.azure = azure
        self.siliconflow = siliconflow
        self.coze = coze
        self.ui = ui
        self.log_level = log_level
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.project_name = project_name
        self.project_description = project_description
        self.project_version = project_version
        self.reload_debug = reload_debug
        self.save_config = save_config

config = Config()