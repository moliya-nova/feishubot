from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, check: bool = True) -> str:
    completed = subprocess.run(  # noqa: S603 - command list is controlled by this script.
        cmd,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{completed.stderr}")
    return completed.stdout.strip()


def _ensure_base_ref(base_ref: str) -> str:
    _run(["git", "fetch", "--no-tags", "--depth=1", "origin", base_ref], check=False)

    origin_ref = f"origin/{base_ref}"
    try:
        _run(["git", "rev-parse", "--verify", origin_ref])
        return origin_ref
    except RuntimeError:
        return base_ref


def _changed_paths(diff_range: str) -> list[str]:
    output = _run(["git", "diff", "--name-only", diff_range])
    if not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _changed_name_status(diff_range: str) -> list[tuple[str, str]]:
    output = _run(["git", "diff", "--name-status", diff_range])
    rows: list[tuple[str, str]] = []
    if not output:
        return rows

    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        path = parts[-1].strip()
        if status and path:
            rows.append((status, path))
    return rows


def _check_merge_commits(diff_range: str, violations: list[str]) -> None:
    merges = _run(["git", "rev-list", "--merges", diff_range])
    if merges:
        violations.append(
            "检测到 PR 分支包含 merge commit。请改用 rebase 保持线性历史，避免引入噪音提交。"
        )


def _check_top_level_module_additions(
    name_status: list[tuple[str, str]], violations: list[str]
) -> None:
    allowed = {
        "__init__.py",
        "app.py",
        "cli.py",
        "config.py",
        "feishu.py",
        "llm_client.py",
        "main.py",
    }
    pattern = re.compile(r"^src/feishubot/([^/]+\.py)$")

    for status, path in name_status:
        if not status.startswith("A"):
            continue
        matched = pattern.match(path)
        if not matched:
            continue
        file_name = matched.group(1)
        if file_name not in allowed:
            violations.append(
                f"不允许在 src/feishubot 顶层新增模块: {path}。"
                "请将新能力放入对应子分层（如 ai/memory、ai/tools 等）。"
            )


def _check_session_history_placement(changed_paths: list[str], violations: list[str]) -> None:
    for path in changed_paths:
        if not path.startswith("src/feishubot/") or not path.endswith(".py"):
            continue
        lower_name = Path(path).name.lower()
        if "session" not in lower_name and "history" not in lower_name:
            continue
        if path.startswith("src/feishubot/ai/memory/"):
            continue
        violations.append(
            f"会话/历史相关模块位置不符合分层规范: {path}。请放入 src/feishubot/ai/memory/ 下。"
        )


def _check_legacy_llm_imports(changed_paths: list[str], violations: list[str]) -> None:
    targets = {"src/feishubot/cli.py", "src/feishubot/app.py"}
    import_pattern = re.compile(
        r"(from\s+feishubot\.llm_client\s+import|import\s+feishubot\.llm_client)"
    )

    for path in changed_paths:
        if path not in targets:
            continue
        file_path = REPO_ROOT / path
        if not file_path.exists():
            continue
        content = file_path.read_text(encoding="utf-8")
        if import_pattern.search(content):
            violations.append(
                f"入口层文件 {path} 重新引入 feishubot.llm_client。"
                "请保持 provider + AgentLoop 单一主流程。"
            )


def _check_root_history_hardcode(changed_paths: list[str], violations: list[str]) -> None:
    patterns = [
        re.compile(r"Path\(\s*['\"]history['\"]\s*\)"),
        re.compile(r"history_dir\s*:\s*str\s*=\s*['\"]history['\"]"),
        re.compile(r"['\"]history/"),
    ]

    for path in changed_paths:
        if not path.startswith("src/") or not path.endswith(".py"):
            continue
        file_path = REPO_ROOT / path
        if not file_path.exists():
            continue
        content = file_path.read_text(encoding="utf-8")
        if any(pattern.search(content) for pattern in patterns):
            violations.append(
                f"检测到根目录 history 路径硬编码: {path}。请改为 memory 分层内配置化路径。"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Architecture guard for pull requests")
    parser.add_argument("--base-ref", default="main", help="PR base branch name")
    args = parser.parse_args()

    base_ref = _ensure_base_ref(args.base_ref)
    diff_range = f"{base_ref}...HEAD"

    changed_paths = _changed_paths(diff_range)
    if not changed_paths:
        print("Architecture guard: no changed files detected, skipping.")
        return 0

    name_status = _changed_name_status(diff_range)
    violations: list[str] = []

    _check_merge_commits(diff_range, violations)
    _check_top_level_module_additions(name_status, violations)
    _check_session_history_placement(changed_paths, violations)
    _check_legacy_llm_imports(changed_paths, violations)
    _check_root_history_hardcode(changed_paths, violations)

    if not violations:
        print("Architecture guard: passed")
        return 0

    print("Architecture guard: failed")
    for index, violation in enumerate(violations, start=1):
        print(f"{index}. {violation}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
