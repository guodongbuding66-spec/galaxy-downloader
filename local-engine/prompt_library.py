from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from runtime_storage import state_dir as runtime_state_dir

PROMPTS_FILENAME = "ai-prompts.json"
SCHEMA_VERSION = 1
MAX_PROMPTS = 100
MAX_TITLE_CHARS = 120
MAX_INSTRUCTION_CHARS = 20_000
MAX_IMPORT_CHARS = 1_000_000
PROMPT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

_DEFAULT_ROWS = (
    ("summary", "结构化摘要", "请只根据输入内容生成结构化摘要，包含核心结论、关键要点、时间线（可判断时）和待核实事项。", "sparkles"),
    ("faq", "FAQ", "根据输入内容生成常见问题与简洁答案；答案必须能从原文找到依据。", "circle-help"),
    ("translation", "翻译", "将输入内容翻译成用户指定的目标语言；保留专有名词、数字、时间和事实关系。", "languages"),
    ("notes", "学习笔记", "将输入内容整理成分层学习笔记，区分核心概念、论据、例子、术语和待复习事项。", "notebook-pen"),
    ("grammar", "语法与文字清理", "修正明显语法、标点、重复和口语冗余，但不要改变事实、语气或添加原文没有的信息。", "spell-check"),
    ("statistics", "数据与事实", "提取数字、日期、指标、人物、组织和可核实事实，按主题分组并保留上下文。", "chart-no-axes-column"),
    ("mind-map", "思维导图", "将输入内容整理为 Markdown 层级思维导图，突出主题、分支、关键关系和因果链。", "network"),
    ("flashcards", "闪卡", "根据输入内容生成用于间隔复习的问答闪卡；每张卡只测试一个明确知识点。", "layers-3"),
)


class PromptLibraryError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    title: str
    instructions: str
    icon: str = "sparkles"
    builtin: bool = False

    def public_payload(self) -> dict[str, Any]:
        return asdict(self)


def _defaults() -> dict[str, PromptTemplate]:
    return {row[0]: PromptTemplate(row[0], row[1], row[2], row[3], True) for row in _DEFAULT_ROWS}


def _state_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / PROMPTS_FILENAME


def _clean_id(value: object) -> str:
    prompt_id = str(value or "").strip().lower()
    if not PROMPT_ID_RE.fullmatch(prompt_id):
        raise PromptLibraryError("Prompt ID 无效")
    return prompt_id


def _clean_title(value: object, fallback: str) -> str:
    title = " ".join(str(value or fallback).split()).strip()[:MAX_TITLE_CHARS]
    return title or fallback


def _clean_instructions(value: object) -> str:
    instructions = str(value or "").strip()[:MAX_INSTRUCTION_CHARS]
    if not instructions:
        raise PromptLibraryError("Prompt 内容不能为空")
    return instructions


def _clean_icon(value: object) -> str:
    icon = str(value or "sparkles").strip().lower()[:40]
    return icon if re.fullmatch(r"[a-z0-9-]{1,40}", icon) else "sparkles"


def _stored_rows(engine_module) -> list[dict[str, Any]]:
    try:
        payload = json.loads(_state_path(engine_module).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION:
        return []
    rows = payload.get("prompts")
    return [item for item in rows[:MAX_PROMPTS] if isinstance(item, dict)] if isinstance(rows, list) else []


def _atomic_store(engine_module, rows: Iterable[dict[str, Any]]) -> None:
    path = _state_path(engine_module)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {"version": SCHEMA_VERSION, "prompts": list(rows)[:MAX_PROMPTS]}
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise


def _normalized_row(row: dict[str, Any]) -> PromptTemplate | None:
    try:
        prompt_id = _clean_id(row.get("id"))
        instructions = _clean_instructions(row.get("instructions"))
    except PromptLibraryError:
        return None
    defaults = _defaults()
    fallback = defaults[prompt_id].title if prompt_id in defaults else prompt_id
    return PromptTemplate(
        id=prompt_id,
        title=_clean_title(row.get("title"), fallback),
        instructions=instructions,
        icon=_clean_icon(row.get("icon")),
        builtin=prompt_id in defaults,
    )


def load_prompt_library(engine_module) -> list[PromptTemplate]:
    result = _defaults()
    custom_order: list[str] = []
    for row in _stored_rows(engine_module):
        prompt = _normalized_row(row)
        if prompt is None:
            continue
        result[prompt.id] = prompt
        if not prompt.builtin and prompt.id not in custom_order:
            custom_order.append(prompt.id)
    builtins = [result[row[0]] for row in _DEFAULT_ROWS]
    customs = [result[prompt_id] for prompt_id in custom_order if prompt_id in result]
    return builtins + customs


def get_prompt(engine_module, prompt_id: object) -> PromptTemplate | None:
    clean_id = str(prompt_id or "").strip().lower()
    return next((item for item in load_prompt_library(engine_module) if item.id == clean_id), None)


def save_prompt(
    engine_module,
    *,
    prompt_id: object,
    title: object,
    instructions: object,
    icon: object = "sparkles",
) -> PromptTemplate:
    clean_id = _clean_id(prompt_id)
    defaults = _defaults()
    fallback = defaults[clean_id].title if clean_id in defaults else clean_id
    prompt = PromptTemplate(
        clean_id,
        _clean_title(title, fallback),
        _clean_instructions(instructions),
        _clean_icon(icon),
        clean_id in defaults,
    )
    rows = [row for row in _stored_rows(engine_module) if str(row.get("id") or "").strip().lower() != clean_id]
    rows.append({"id": prompt.id, "title": prompt.title, "instructions": prompt.instructions, "icon": prompt.icon})
    _atomic_store(engine_module, rows)
    return prompt


def delete_prompt(engine_module, prompt_id: object) -> bool:
    clean_id = _clean_id(prompt_id)
    rows = _stored_rows(engine_module)
    kept = [row for row in rows if str(row.get("id") or "").strip().lower() != clean_id]
    if len(kept) == len(rows):
        return False
    _atomic_store(engine_module, kept)
    return True


def duplicate_prompt(
    engine_module,
    prompt_id: object,
    *,
    new_id: object = "",
    title: object = "",
) -> PromptTemplate:
    source = get_prompt(engine_module, prompt_id)
    if source is None:
        raise PromptLibraryError("源 Prompt 不存在")
    existing = {item.id for item in load_prompt_library(engine_module)}
    if str(new_id or "").strip():
        target_id = _clean_id(new_id)
        if target_id in existing:
            raise PromptLibraryError("Prompt ID 已存在")
    else:
        base = re.sub(r"[^a-z0-9_-]", "-", f"{source.id}-copy".lower())[:58].strip("-") or "prompt-copy"
        target_id = base
        suffix = 2
        while target_id in existing:
            target_id = f"{base[:56]}-{suffix}"
            suffix += 1
        target_id = _clean_id(target_id)
    return save_prompt(
        engine_module,
        prompt_id=target_id,
        title=title or f"{source.title} Copy",
        instructions=source.instructions,
        icon=source.icon,
    )


def export_prompt_library(engine_module) -> str:
    rows = [
        {"id": item.id, "title": item.title, "instructions": item.instructions, "icon": item.icon}
        for item in load_prompt_library(engine_module)
    ]
    return json.dumps({"version": SCHEMA_VERSION, "prompts": rows}, ensure_ascii=False, indent=2)


def import_prompt_library(engine_module, payload: object, *, replace: bool = False) -> int:
    if isinstance(payload, str):
        if len(payload) > MAX_IMPORT_CHARS:
            raise PromptLibraryError("Prompt 导入内容过大")
        try:
            parsed = json.loads(payload)
        except ValueError as exc:
            raise PromptLibraryError("Prompt 导入 JSON 无效") from exc
    else:
        parsed = payload
    if isinstance(parsed, dict) and parsed.get("version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise PromptLibraryError("Prompt 导入版本不受支持")
    rows = parsed.get("prompts") if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        raise PromptLibraryError("Prompt 导入格式无效")
    accepted: list[PromptTemplate] = []
    seen: set[str] = set()
    for row in rows[:MAX_PROMPTS]:
        if not isinstance(row, dict):
            continue
        prompt = _normalized_row(row)
        if prompt is None or prompt.id in seen:
            continue
        seen.add(prompt.id)
        accepted.append(prompt)
    if not accepted and rows:
        raise PromptLibraryError("Prompt 导入内容中没有有效模板")

    current = [] if replace else _stored_rows(engine_module)
    incoming_ids = {item.id for item in accepted}
    merged = [row for row in current if str(row.get("id") or "").strip().lower() not in incoming_ids]
    merged.extend(
        {"id": item.id, "title": item.title, "instructions": item.instructions, "icon": item.icon}
        for item in accepted
    )
    _atomic_store(engine_module, merged)
    return len(accepted)


def restore_default_prompts(engine_module) -> None:
    path = _state_path(engine_module)
    with suppress(FileNotFoundError):
        path.unlink()


def run_prompt_library_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                target = root / "state"
                target.mkdir(exist_ok=True)
                return target

        defaults = load_prompt_library(Engine)
        assert [item.id for item in defaults] == [row[0] for row in _DEFAULT_ROWS]
        assert all(item.builtin for item in defaults)

        custom = save_prompt(Engine, prompt_id="meeting-notes", title="Meeting Notes", instructions="Extract decisions and actions.")
        assert not custom.builtin
        assert get_prompt(Engine, "meeting-notes") == custom

        overridden = save_prompt(Engine, prompt_id="summary", title="My Summary", instructions="Custom summary instructions")
        assert overridden.builtin and get_prompt(Engine, "summary").title == "My Summary"
        assert delete_prompt(Engine, "summary")
        assert get_prompt(Engine, "summary").title == "结构化摘要"

        copied = duplicate_prompt(Engine, "meeting-notes")
        assert copied.id != custom.id and not copied.builtin
        assert copied.instructions == custom.instructions

        exported = export_prompt_library(Engine)
        restore_default_prompts(Engine)
        assert get_prompt(Engine, "meeting-notes") is None
        count = import_prompt_library(Engine, exported, replace=True)
        assert count >= len(_DEFAULT_ROWS)
        assert get_prompt(Engine, "meeting-notes") is not None

        try:
            save_prompt(Engine, prompt_id="../bad", title="Bad", instructions="Bad")
        except PromptLibraryError:
            pass
        else:
            raise AssertionError("unsafe prompt id was accepted")
