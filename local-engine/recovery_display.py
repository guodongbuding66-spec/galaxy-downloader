from __future__ import annotations

from typing import Any, Callable

import desktop_extras as extras
from recovery_policy import effective_network_preferences

RETRY_DISPLAY = {
    "standard": "标准（10 次重试）",
    "resilient": "弱网增强（20 次重试）",
    "fast-fail": "快速失败（5 次重试）",
}


def _has_job_override(job: Any | None) -> bool:
    return bool(
        job
        and any(
            value is not None
            for value in (
                getattr(job, "network_retry_profile", None),
                getattr(job, "rate_limit_mbps", None),
                getattr(job, "concurrent_fragments", None),
            )
        )
    )


def install_recovery_display(engine_module):
    """Make task details show the transport settings the active Job really uses.

    desktop_runtime adds the network rows from persistent workspace preferences.
    Smart retry can override those values for one Job. This final display layer
    replaces only those three rows, so the UI cannot claim Standard/4 while the
    downloader is actually running Resilient/2 for a recovery attempt.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_recovery_display_installed", False):
        return window_cls

    original_job_lines: Callable[[Any], list[tuple[str, str]]] = extras._job_lines

    def job_lines(window) -> list[tuple[str, str]]:
        lines = original_job_lines(window)
        job = getattr(window, "job", None)
        if job is None:
            return lines
        preferences = effective_network_preferences(engine_module, job)
        profile = str(preferences.get("networkRetryProfile") or "standard")
        fragments = int(preferences.get("concurrentFragments") or 4)
        rate = int(preferences.get("rateLimitMbps") or 0)
        replacements = {
            "网络重试": RETRY_DISPLAY.get(profile, profile),
            "并发分片": str(fragments),
            "速度上限": "不限速" if rate <= 0 else f"{rate} Mbps",
        }
        rendered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for name, value in lines:
            if name in replacements:
                rendered.append((name, replacements[name]))
                seen.add(name)
            else:
                rendered.append((name, value))
        for name in ("网络重试", "并发分片", "速度上限"):
            if name not in seen:
                rendered.append((name, replacements[name]))
        if _has_job_override(job):
            rendered.append(("恢复覆盖", "仅当前任务"))
        return rendered

    extras._job_lines = job_lines
    window_cls._galaxy_recovery_display_installed = True
    engine_module._galaxy_recovery_display_installed = True
    return window_cls


def run_recovery_display_self_test() -> None:
    class Job:
        network_retry_profile = "resilient"
        rate_limit_mbps = 5
        concurrent_fragments = 1

    assert _has_job_override(Job()) is True
    assert _has_job_override(None) is False
