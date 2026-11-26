"""Monitorización de CPU y RAM sin dependencias nuevas.

``psutil`` no está instalado. En Windows se consulta ``GlobalMemoryStatusEx`` por
ctypes y en Linux ``/proc/meminfo``. El porcentaje de CPU es una media de carga
del sistema; si no se puede medir se devuelve ``None`` en lugar de inventarlo.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path


def _windows_memory() -> tuple[float, float] | None:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (AttributeError, OSError, ValueError):
        return None
    return status.ullTotalPhys / (1024 * 1024), status.ullAvailPhys / (1024 * 1024)


def _linux_memory() -> tuple[float, float] | None:
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            values[key] = float(rest.strip().split()[0]) / 1024.0
        total = values.get("MemTotal", 0.0)
        available = values.get("MemAvailable", values.get("MemFree", 0.0))
        return (total, available) if total else None
    except (OSError, ValueError):
        return None


def _load_average() -> float | None:
    try:
        return round(os.getloadavg()[0] / max(1, os.cpu_count() or 1) * 100.0, 1)
    except (AttributeError, OSError):
        return None


def snapshot() -> dict:
    memory = _windows_memory() if sys.platform == "win32" else _linux_memory()
    total = round(memory[0]) if memory else None
    available = round(memory[1]) if memory else None
    percent = round((1 - available / total) * 100, 1) if total and available else None
    project_root = Path(__file__).resolve().parents[3]
    try:
        disk = shutil.disk_usage(str(project_root))
        free_gb = round(disk.free / (1024**3), 1)
    except OSError:
        free_gb = None
    return {
        "cpu_count": os.cpu_count(),
        "cpu_percent": _load_average(),
        "ram_total_mb": total,
        "ram_available_mb": available,
        "ram_percent": percent,
        "disk_free_gb": free_gb,
    }


def guard(min_free_mb: int = 900) -> tuple[bool, str]:
    """Comprueba que hay memoria suficiente antes de cargar modelos."""
    data = snapshot()
    available = data.get("ram_available_mb")
    if available is not None and available < min_free_mb:
        return False, (
            f"Memoria disponible baja ({available} MB). Cierra otras aplicaciones "
            f"o usa el perfil económico."
        )
    return True, "Recursos suficientes"
