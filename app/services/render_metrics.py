"""Best-effort per-process resource snapshots without an extra dependency."""

from __future__ import annotations

import os
import platform
import sys
import time


def cpu_seconds() -> float:
    values = os.times()
    return float(values.user + values.system + values.children_user + values.children_system)


def resident_memory_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            get_memory_info = psapi.GetProcessMemoryInfo
            get_memory_info.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_Counters),
                wintypes.DWORD,
            ]
            get_memory_info.restype = wintypes.BOOL
            process = kernel32.GetCurrentProcess()
            ok = get_memory_info(process, ctypes.byref(counters), counters.cb)
            return int(counters.WorkingSetSize) if ok else None
        try:
            with open("/proc/self/statm", encoding="ascii") as source:
                resident_pages = int(source.read().split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            import resource

            max_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return max_rss if platform.system() == "Darwin" else max_rss * 1024
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def start_snapshot() -> dict:
    return {
        "wall_time": time.perf_counter(),
        "cpu_seconds": cpu_seconds(),
        "resident_memory_bytes": resident_memory_bytes(),
    }


def finish_snapshot(start: dict, *, output_path: str, duration: float, fps: int) -> dict:
    elapsed = max(0.0, time.perf_counter() - start["wall_time"])
    try:
        output_bytes = os.path.getsize(output_path)
    except OSError:
        output_bytes = None
    current_rss = resident_memory_bytes()
    return {
        "render_elapsed_seconds": round(elapsed, 3),
        "process_cpu_seconds": round(max(0.0, cpu_seconds() - start["cpu_seconds"]), 3),
        "resident_memory_bytes_start": start["resident_memory_bytes"],
        "resident_memory_bytes_end": current_rss,
        "output_bytes": output_bytes,
        "output_fps": fps,
        "estimated_encode_fps": round(duration * fps / elapsed, 2) if elapsed > 0 else None,
    }
