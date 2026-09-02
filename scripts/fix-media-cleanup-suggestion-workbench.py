from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "local-engine" / "media_cleanup_workbench.py"
MARKER = 'cleanup_status_var.set("自动建议已忽略")\n        set_running(False)'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"fix anchor missing: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("cleanup suggestion workbench state already hardened")
        return

    text = text.replace("    CleanupRegionSuggestion,\n", "", 1)
    text = replace_once(
        text,
        '''        suggestion_var.set(message)\n        if "accept_suggestion_button" in locals():\n            set_running(media_cleanup_active(window))\n''',
        '''        suggestion_var.set(message)\n''',
        "clear suggestion controls",
    )
    text = replace_once(
        text,
        '''        if busy:\n            choose_button.state(["disabled"])\n''',
        '''        if busy:\n            suggestion_profile.configure(state="disabled")\n            choose_button.state(["disabled"])\n''',
        "disable profile while busy",
    )
    text = replace_once(
        text,
        '''        else:\n            choose_button.state(["!disabled"])\n''',
        '''        else:\n            suggestion_profile.configure(state="readonly")\n            choose_button.state(["!disabled"])\n''',
        "restore profile after busy",
    )
    text = replace_once(
        text,
        '''        clear_suggestions(message="已忽略自动建议，可重新分析或手动画框")\n        cleanup_status_var.set("自动建议已忽略")\n''',
        '''        clear_suggestions(message="已忽略自动建议，可重新分析或手动画框")\n        cleanup_status_var.set("自动建议已忽略")\n        set_running(False)\n''',
        "refresh after ignore",
    )
    text = replace_once(
        text,
        '''    def on_press(event) -> None:\n        if media_cleanup_active(window) or state.get("plan") is None:\n''',
        '''    def on_press(event) -> None:\n        if media_cleanup_active(window) or state.get("suggestion_running") or state.get("plan") is None:\n''',
        "block drawing while suggesting",
    )
    text = replace_once(
        text,
        '''    def undo_region() -> None:\n        if not state["regions"] or media_cleanup_active(window):\n''',
        '''    def undo_region() -> None:\n        if not state["regions"] or media_cleanup_active(window) or state.get("suggestion_running"):\n''',
        "block undo while suggesting",
    )

    TARGET.write_text(text, encoding="utf-8")
    print("hardened media cleanup suggestion workbench state")


if __name__ == "__main__":
    main()
