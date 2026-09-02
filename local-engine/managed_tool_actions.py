from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from ffmpeg_manager import reset_managed_ffmpeg, seed_managed_ffmpeg
from ffmpeg_online_installer import install_managed_ffmpeg_online
from ffmpeg_update_status import check_ffmpeg_update
from managed_tool_registry import registered_tool_specs
from tool_manager import reset_managed_ytdlp, seed_managed_ytdlp, update_managed_ytdlp

MANAGED_TOOL_ACTIONS = {"check", "install", "update", "seed", "reset"}
_TOOL_ACTIONS: dict[str, tuple[str, ...]] = {
    "ffmpeg": ("check", "install", "update", "seed", "reset"),
    "yt-dlp": ("seed", "update", "reset"),
}
_NETWORK_ACTIONS = {
    ("ffmpeg", "check"),
    ("ffmpeg", "install"),
    ("ffmpeg", "update"),
    ("yt-dlp", "update"),
}
_MUTATING_ACTIONS = {
    ("ffmpeg", "install"),
    ("ffmpeg", "update"),
    ("ffmpeg", "seed"),
    ("ffmpeg", "reset"),
    ("yt-dlp", "seed"),
    ("yt-dlp", "update"),
    ("yt-dlp", "reset"),
}


@dataclass(frozen=True)
class ManagedToolActionRequest:
    tool: str
    action: str
    user_initiated: bool
    channel: str | None = None


@dataclass(frozen=True)
class ManagedToolActionResult:
    tool: str
    action: str
    ok: bool
    changed: bool
    state: str
    source: str
    version: str | None
    current_release_tag: str | None
    available_version: str | None
    available_release_tag: str | None
    update_available: bool | None
    network_action: bool
    message: str


@dataclass(frozen=True)
class ManagedToolActionAdapters:
    ffmpeg_check: Callable[..., object] = check_ffmpeg_update
    ffmpeg_install: Callable[..., object] = install_managed_ffmpeg_online
    ffmpeg_seed: Callable[..., object] = seed_managed_ffmpeg
    ffmpeg_reset: Callable[..., object] = reset_managed_ffmpeg
    ytdlp_seed: Callable[..., object] = seed_managed_ytdlp
    ytdlp_update: Callable[..., object] = update_managed_ytdlp
    ytdlp_reset: Callable[..., object] = reset_managed_ytdlp


def _known_tools() -> frozenset[str]:
    return frozenset(spec.tool for spec in registered_tool_specs())


def supported_managed_tool_actions(tool: str) -> tuple[str, ...]:
    return _TOOL_ACTIONS.get(str(tool or "").strip().lower(), ())


def managed_tool_action_policy(tool: str, action: str) -> dict[str, bool]:
    key = (str(tool or "").strip().lower(), str(action or "").strip().lower())
    return {
        "network": key in _NETWORK_ACTIONS,
        "mutating": key in _MUTATING_ACTIONS,
        "userInitiationRequired": key[1] in MANAGED_TOOL_ACTIONS,
    }


def _result(
    request: ManagedToolActionRequest,
    *,
    ok: bool,
    changed: bool = False,
    state: str,
    source: str = "unknown",
    version: str | None = None,
    current_release_tag: str | None = None,
    available_version: str | None = None,
    available_release_tag: str | None = None,
    update_available: bool | None = None,
    network_action: bool = False,
    message: str,
) -> ManagedToolActionResult:
    return ManagedToolActionResult(
        tool=str(request.tool or "").strip().lower(),
        action=str(request.action or "").strip().lower(),
        ok=bool(ok),
        changed=bool(changed),
        state=state,
        source=source,
        version=version,
        current_release_tag=current_release_tag,
        available_version=available_version,
        available_release_tag=available_release_tag,
        update_available=update_available,
        network_action=bool(network_action),
        message=str(message or "")[:1000],
    )


def _normalize_update_status(request: ManagedToolActionRequest, native: object, *, network: bool) -> ManagedToolActionResult:
    return _result(
        request,
        ok=bool(getattr(native, "ok", False)),
        changed=False,
        state=str(getattr(native, "state", "error") or "error"),
        source=str(getattr(native, "current_source", "unknown") or "unknown"),
        version=getattr(native, "current_version", None),
        current_release_tag=getattr(native, "current_release_tag", None),
        available_version=getattr(native, "available_version", None),
        available_release_tag=getattr(native, "available_release_tag", None),
        update_available=getattr(native, "update_available", None),
        network_action=network,
        message=str(getattr(native, "message", "") or ""),
    )


def _normalize_action_result(request: ManagedToolActionRequest, native: object, *, network: bool) -> ManagedToolActionResult:
    ok = bool(getattr(native, "ok", False))
    return _result(
        request,
        ok=ok,
        changed=bool(getattr(native, "changed", False)),
        state="completed" if ok else "error",
        source=str(getattr(native, "source", "unknown") or "unknown"),
        version=getattr(native, "version", None),
        network_action=network,
        message=str(getattr(native, "message", "") or ""),
    )


def perform_managed_tool_action(
    engine_module,
    request: ManagedToolActionRequest,
    *,
    adapters: ManagedToolActionAdapters | None = None,
) -> ManagedToolActionResult:
    """Run one explicitly requested managed-tool action through a stable contract.

    This dispatcher is intentionally not an automation scheduler. Every supported
    action either contacts a provider, mutates a managed tool, or both, so the
    caller must explicitly assert `user_initiated=True`. A rejected request never
    invokes its adapter. `network_action` means the invoked action contract permits
    network access; it does not claim that the underlying adapter completed a
    network request before returning or failing.
    """
    tool = str(request.tool or "").strip().lower()
    action = str(request.action or "").strip().lower()
    normalized = ManagedToolActionRequest(tool=tool, action=action, user_initiated=bool(request.user_initiated), channel=request.channel)

    if tool not in _known_tools():
        return _result(normalized, ok=False, state="unsupported-tool", message=f"Unsupported managed tool: {tool or '<empty>'}")
    if action not in MANAGED_TOOL_ACTIONS:
        return _result(normalized, ok=False, state="unsupported-action", message=f"Unsupported managed tool action: {action or '<empty>'}")
    if action not in supported_managed_tool_actions(tool):
        return _result(normalized, ok=False, state="unsupported-action", message=f"{tool} does not support the {action} action.")
    if not normalized.user_initiated:
        return _result(
            normalized,
            ok=False,
            state="user-initiation-required",
            message=f"The {tool}/{action} action requires an explicit user initiation signal.",
        )
    if normalized.channel is not None and not (tool == "yt-dlp" and action == "update"):
        return _result(normalized, ok=False, state="invalid-request", message="An update channel is only valid for yt-dlp update actions.")

    selected = adapters or ManagedToolActionAdapters()
    network = (tool, action) in _NETWORK_ACTIONS
    try:
        if tool == "ffmpeg":
            if action == "check":
                return _normalize_update_status(normalized, selected.ffmpeg_check(engine_module), network=network)
            if action in {"install", "update"}:
                return _normalize_action_result(normalized, selected.ffmpeg_install(engine_module), network=network)
            if action == "seed":
                return _normalize_action_result(normalized, selected.ffmpeg_seed(engine_module), network=network)
            if action == "reset":
                return _normalize_action_result(normalized, selected.ffmpeg_reset(engine_module), network=network)

        if tool == "yt-dlp":
            if action == "seed":
                return _normalize_action_result(normalized, selected.ytdlp_seed(engine_module), network=network)
            if action == "update":
                channel = str(normalized.channel or "stable").strip().lower() or "stable"
                return _normalize_action_result(
                    normalized,
                    selected.ytdlp_update(engine_module, channel=channel),
                    network=network,
                )
            if action == "reset":
                return _normalize_action_result(normalized, selected.ytdlp_reset(engine_module), network=network)
    except Exception as exc:
        return _result(
            normalized,
            ok=False,
            state="error",
            network_action=network,
            message=f"Managed tool action failed before a normalized result was returned: {exc}",
        )

    return _result(normalized, ok=False, state="unsupported-action", message=f"No adapter is registered for {tool}/{action}.")


def public_managed_tool_action_result(result: ManagedToolActionResult) -> dict[str, object]:
    payload = asdict(result)
    return {
        "tool": payload["tool"],
        "action": payload["action"],
        "ok": payload["ok"],
        "changed": payload["changed"],
        "state": payload["state"],
        "source": payload["source"],
        "version": payload["version"],
        "currentReleaseTag": payload["current_release_tag"],
        "availableVersion": payload["available_version"],
        "availableReleaseTag": payload["available_release_tag"],
        "updateAvailable": payload["update_available"],
        "networkAction": payload["network_action"],
        "message": payload["message"],
    }


def run_managed_tool_actions_self_test() -> None:
    called = {"count": 0}

    def forbidden(*_args, **_kwargs):
        called["count"] += 1
        raise AssertionError("adapter should not run")

    adapters = ManagedToolActionAdapters(
        ffmpeg_check=forbidden,
        ffmpeg_install=forbidden,
        ffmpeg_seed=forbidden,
        ffmpeg_reset=forbidden,
        ytdlp_seed=forbidden,
        ytdlp_update=forbidden,
        ytdlp_reset=forbidden,
    )
    rejected = perform_managed_tool_action(
        object(),
        ManagedToolActionRequest("ffmpeg", "check", False),
        adapters=adapters,
    )
    assert rejected.state == "user-initiation-required"
    assert rejected.network_action is False
    assert called["count"] == 0
