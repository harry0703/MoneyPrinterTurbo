# -*- mode: python ; coding: utf-8 -*-
"""影创AI 桌面端后端打包规格（PyInstaller onedir）。

将 app/webui(含 Main.py 与 i18n)/resource/config.example.toml 作为 data 打入，
并通过 collect_all / hiddenimports 收集第三方与动态导入的依赖。
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas = []
binaries = []
hiddenimports = []

# 项目自身的源码与资源，以 data 形式保留目录结构
for target in ("webui", "resource", "cli"):
    src = os.path.join(ROOT, target)
    if os.path.isdir(src):
        datas.append((src, target))
datas.append((os.path.join(ROOT, "config.example.toml"), "."))

# app 包内的非源码数据文件（如 app/services/data/azure_voices.json 等），
# 供运行时按 __file__ 相对路径读取。collect_data_files 依赖 app 能在 spec
# 评估期被导入，往往拿不到；这里直接按 ROOT 相对路径显式收集。
for app_data_dir in (
    os.path.join(ROOT, "app", "services", "data"),
):
    if os.path.isdir(app_data_dir):
        rel = os.path.relpath(app_data_dir, ROOT)
        datas.append((app_data_dir, rel))

# 需要随包携带数据/子模块的第三方包
for pkg in (
    "streamlit",
    "streamlit_tour",
    "altair",
    "plotly",
    "moviepy",
    "faster_whisper",
    "onnxruntime",
    "edge_tts",
    "imageio",
    "imageio_ffmpeg",
    "PIL",
    "loguru",
    "pydub",
    "toml",
    "uvicorn",
    "fastapi",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] collect_all failed for {pkg}: {exc}")

# 动态导入/扩展相关的隐藏导入
hiddenimports += collect_submodules("app")
# webui/Main.py 是作为 data 打包、由 streamlit 直接运行的脚本，其 import 不会
# 被入口分析发现。这里显式补上它依赖的 app 子模块，通常 collect_submodules
# 已覆盖，但为了稳妥再次声明（与下方把 Main.py 加入 scripts 分析双保险）。
hiddenimports += [
    "app.services.cache_manager",
    "app.services.webui_task",
    "app.services.version_checker",
    "dashscope",
    "redis",
    "socksio",
    "litellm",
    "google.genai",
    "azure.cognitiveservices.speech",
    "elevenlabs",
    "openai",
    "ctranslate2",
    "yaml",
    "requests",
    "fastapi",
]

a = Analysis(
    # 第二个脚本 webui/Main.py 仅用于让 PyInstaller 分析其完整 import 依赖
    # （缓存管理/版本检查/WebUI 任务等仅在 WebUI 中引用的模块）；launcher 仍
    # 是唯一入口，Main.py 仍以 data 形态被打包并由 streamlit 运行。
    [
        "launcher.py",
        os.path.join(ROOT, "webui", "Main.py"),
    ],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # av(PyAV) 的 filter/filter 与 filter/graph 互为 Cython 循环类型导入，
    # 在 PyInstaller 冻结导入器下会间歇性死锁。默认流程(edge 字幕 + ffmpeg
    # CLI 合成)并不需要 av，仅可选的 faster_whisper 解码音频时才用到，故直接
    # 排除，避免启动卡死。
    excludes=["av"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mpt-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="mpt-backend",
)
