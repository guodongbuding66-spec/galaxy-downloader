from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from platform_paths import get_paths
from state_backup import (
    StateBackupError,
    create_state_backup,
    restore_state_backup,
    run_state_backup_self_test,
    validate_state_backup,
)


class RuntimeStateContext:
    @staticmethod
    def app_dir() -> Path:
        return get_paths().program_dir

    @staticmethod
    def data_dir() -> Path:
        return get_paths().data_dir

    @staticmethod
    def state_dir() -> Path:
        return get_paths().state_dir


def _print_result(result: dict[str, object]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("Galaxy Local Engine · Backup / Restore")
    root.geometry("620x330")
    root.minsize(560, 300)
    root.configure(padx=24, pady=22)

    tk.Label(root, text="Backup / Restore", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    tk.Label(
        root,
        text=(
            "备份只包含已登记的应用状态；诊断日志、Telegram 密钥和未知文件不会进入备份。\n"
            "恢复为完整快照恢复。执行恢复前请关闭 Galaxy Local Engine。"
        ),
        justify="left",
        wraplength=550,
        font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(8, 18))

    status = tk.StringVar(value=f"State: {RuntimeStateContext.state_dir()}")
    tk.Label(root, textvariable=status, justify="left", wraplength=550, font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 14))

    def backup() -> None:
        target = filedialog.asksaveasfilename(
            parent=root,
            title="保存状态备份",
            defaultextension=".galaxy-state.zip",
            filetypes=[("Galaxy State Backup", "*.galaxy-state.zip"), ("ZIP", "*.zip"), ("All files", "*.*")],
        )
        if not target:
            return
        try:
            result = create_state_backup(RuntimeStateContext, target)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Galaxy Local Engine", f"备份失败：\n{exc}", parent=root)
            return
        status.set(f"备份完成：{result['files']} files · {result['path']}")
        messagebox.showinfo("Galaxy Local Engine", "状态备份已完成并通过写入校验。", parent=root)

    def restore() -> None:
        source = filedialog.askopenfilename(
            parent=root,
            title="选择状态备份",
            filetypes=[("Galaxy State Backup", "*.galaxy-state.zip *.zip"), ("All files", "*.*")],
        )
        if not source:
            return
        try:
            verified = validate_state_backup(source)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Galaxy Local Engine", f"备份校验失败，不会修改当前状态：\n{exc}", parent=root)
            return
        if not messagebox.askyesno(
            "Galaxy Local Engine",
            f"备份已通过校验，共 {verified['files']} 个状态文件。\n\n"
            "恢复会把已登记状态还原到该快照；不在快照中的已登记状态会被删除。\n"
            "请确认 Galaxy Local Engine 已完全关闭。继续？",
            parent=root,
        ):
            return
        try:
            result = restore_state_backup(RuntimeStateContext, source)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Galaxy Local Engine", f"恢复失败；程序已尝试回滚原状态：\n{exc}", parent=root)
            return
        status.set(f"恢复完成：{result['files']} files · {result['path']}")
        messagebox.showinfo("Galaxy Local Engine", "状态恢复完成。现在可以重新启动 Galaxy Local Engine。", parent=root)

    def validate() -> None:
        source = filedialog.askopenfilename(
            parent=root,
            title="选择要验证的状态备份",
            filetypes=[("Galaxy State Backup", "*.galaxy-state.zip *.zip"), ("All files", "*.*")],
        )
        if not source:
            return
        try:
            result = validate_state_backup(source)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Galaxy Local Engine", f"备份无效：\n{exc}", parent=root)
            return
        status.set(f"校验通过：{result['files']} files · {result['path']}")
        messagebox.showinfo("Galaxy Local Engine", "备份结构、文件清单、大小和 SHA-256 校验均通过。", parent=root)

    buttons = tk.Frame(root)
    buttons.pack(fill="x", pady=(6, 0))
    tk.Button(buttons, text="创建备份", command=backup, width=14).pack(side="left")
    tk.Button(buttons, text="验证备份", command=validate, width=14).pack(side="left", padx=(10, 0))
    tk.Button(buttons, text="恢复备份", command=restore, width=14).pack(side="left", padx=(10, 0))
    tk.Button(buttons, text="关闭", command=root.destroy, width=10).pack(side="right")

    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Galaxy Local Engine state backup/restore utility")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--backup", metavar="PATH")
    group.add_argument("--restore", metavar="PATH")
    group.add_argument("--validate", metavar="PATH")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            run_state_backup_self_test()
            _print_result({"ok": True, "selfTest": "state-backup"})
            return 0
        if args.backup:
            _print_result(create_state_backup(RuntimeStateContext, args.backup))
            return 0
        if args.validate:
            _print_result(validate_state_backup(args.validate))
            return 0
        if args.restore:
            _print_result(restore_state_backup(RuntimeStateContext, args.restore))
            return 0
        return _run_gui()
    except (StateBackupError, OSError, sqlite3.Error) as exc:  # type: ignore[name-defined]
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    # Imported lazily so the GUI path stays small, while CLI errors still classify SQLite failures.
    import sqlite3

    raise SystemExit(main())
