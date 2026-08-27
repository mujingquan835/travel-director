"""Low-overhead environment and process-tree resource telemetry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import platform
from pathlib import Path
import sys
from threading import Event, Lock, Thread
import time
from typing import Any

import psutil


def collect_environment() -> dict[str, Any]:
    """Return stable, local-only host facts useful for benchmark comparison."""

    memory = psutil.virtual_memory()
    return {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "executable_name": Path(sys.executable).name,
        "cpu_logical": psutil.cpu_count(logical=True),
        "cpu_physical": psutil.cpu_count(logical=False),
        "memory_total_bytes": memory.total,
    }


@dataclass(frozen=True)
class ResourceSnapshot:
    sample_interval_ms: int
    sample_count: int
    wall_ms: float
    process_user_cpu_ms: float
    process_system_cpu_ms: float
    peak_process_tree_rss_bytes: int
    final_process_rss_bytes: int
    read_bytes: int | None
    write_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResourceMonitor:
    """Sample this process and its children without retaining a time series."""

    def __init__(self, interval_seconds: float = 0.1) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self.process = psutil.Process()
        self._stop = Event()
        self._lock = Lock()
        self._peak_rss = 0
        self._sample_count = 0
        self._thread: Thread | None = None
        self._started_at = 0.0
        self._cpu_before = None
        self._io_before = None

    def _sample(self) -> None:
        processes = [self.process]
        try:
            processes.extend(self.process.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        rss = 0
        for process in processes:
            try:
                rss += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        with self._lock:
            self._peak_rss = max(self._peak_rss, rss)
            self._sample_count += 1

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def start(self) -> "ResourceMonitor":
        if self._thread is not None:
            raise RuntimeError("resource monitor has already started")
        self._started_at = time.perf_counter()
        self._cpu_before = self.process.cpu_times()
        try:
            self._io_before = self.process.io_counters()
        except (AttributeError, psutil.AccessDenied, NotImplementedError):
            self._io_before = None
        self._sample()
        self._thread = Thread(target=self._run, name="scanner-resource-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> ResourceSnapshot:
        if self._thread is None or self._cpu_before is None:
            raise RuntimeError("resource monitor has not started")
        self._stop.set()
        self._thread.join(timeout=max(self.interval_seconds * 2, 0.2))
        self._sample()
        wall_ms = (time.perf_counter() - self._started_at) * 1000.0
        cpu_after = self.process.cpu_times()
        try:
            io_after = self.process.io_counters()
        except (AttributeError, psutil.AccessDenied, NotImplementedError):
            io_after = None
        read_bytes = None
        write_bytes = None
        if self._io_before is not None and io_after is not None:
            read_bytes = max(0, io_after.read_bytes - self._io_before.read_bytes)
            write_bytes = max(0, io_after.write_bytes - self._io_before.write_bytes)
        with self._lock:
            peak_rss = self._peak_rss
            sample_count = self._sample_count
        try:
            final_rss = self.process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            final_rss = 0
        peak_rss = max(peak_rss, final_rss)
        return ResourceSnapshot(
            sample_interval_ms=round(self.interval_seconds * 1000),
            sample_count=sample_count,
            wall_ms=wall_ms,
            process_user_cpu_ms=max(0.0, (cpu_after.user - self._cpu_before.user) * 1000.0),
            process_system_cpu_ms=max(0.0, (cpu_after.system - self._cpu_before.system) * 1000.0),
            peak_process_tree_rss_bytes=peak_rss,
            final_process_rss_bytes=final_rss,
            read_bytes=read_bytes,
            write_bytes=write_bytes,
        )


def accelerator_memory(actual_device: str) -> dict[str, int | str | None]:
    """Capture accelerator memory if the active local backend exposes it."""

    output: dict[str, int | str | None] = {
        "actual_device": actual_device,
        "current_allocated_bytes": None,
        "driver_allocated_bytes": None,
    }
    if actual_device != "mps":
        return output
    try:
        import torch

        output["current_allocated_bytes"] = int(torch.mps.current_allocated_memory())
        driver_allocated = getattr(torch.mps, "driver_allocated_memory", None)
        if driver_allocated is not None:
            output["driver_allocated_bytes"] = int(driver_allocated())
    except (ImportError, RuntimeError):
        pass
    return output
