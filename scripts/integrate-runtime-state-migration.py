from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT / "local-engine"
IMPORT_LINE = "from runtime_storage import state_dir as runtime_state_dir\n"
LEGACY_EXPR = 'engine_module.app_dir() / "state"'
RUNTIME_EXPR = "runtime_state_dir(engine_module)"


def insert_runtime_storage_import(text: str) -> str:
    if IMPORT_LINE in text:
        return text
    anchor = "from __future__ import annotations\n\n"
    if anchor not in text:
        raise RuntimeError("missing future-annotations import anchor")
    return text.replace(anchor, anchor + IMPORT_LINE + "\n", 1)


def migrate_state_consumers() -> list[str]:
    changed: list[str] = []
    for path in sorted(ENGINE_DIR.glob("*.py")):
        if path.name == "runtime_storage.py":
            continue
        text = path.read_text(encoding="utf-8")
        if LEGACY_EXPR not in text:
            continue
        updated = insert_runtime_storage_import(text).replace(LEGACY_EXPR, RUNTIME_EXPR)
        path.write_text(updated, encoding="utf-8")
        changed.append(path.name)
    if changed and len(changed) < 5:
        raise RuntimeError(f"expected the established state consumers, changed={changed}")
    leftovers = [
        path.name
        for path in sorted(ENGINE_DIR.glob("*.py"))
        if path.name != "runtime_storage.py" and LEGACY_EXPR in path.read_text(encoding="utf-8")
    ]
    if leftovers:
        raise RuntimeError(f"legacy state paths remain: {leftovers}")
    return changed


def patch_entrypoint() -> None:
    path = ENGINE_DIR / "entrypoint.py"
    text = path.read_text(encoding="utf-8")
    import_line = "from runtime_storage import run_runtime_storage_self_test\n"
    if import_line not in text:
        anchor = "from runtime_health import install_runtime_health, run_runtime_health_self_test\n"
        if anchor not in text:
            raise RuntimeError("entrypoint runtime_health import anchor missing")
        text = text.replace(anchor, anchor + import_line, 1)
    call = "    run_runtime_storage_self_test()\n"
    if call not in text:
        anchor = "    run_runtime_paths_policy_self_test()\n"
        if anchor not in text:
            raise RuntimeError("entrypoint runtime paths self-test anchor missing")
        text = text.replace(anchor, anchor + call, 1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    changed = migrate_state_consumers()
    patch_entrypoint()
    print("migrated runtime state consumers:", ", ".join(changed) if changed else "already migrated")
