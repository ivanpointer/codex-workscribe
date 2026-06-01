from __future__ import annotations

import json
import shutil
import sys
import subprocess
from pathlib import Path
from typing import Any

from workscribe.config import ROOT_CONFIG_FILENAME, WorkscribeError


WORKSCRIBE_MARKER = "workscribe-managed"
GIT_HOOKS = ("post-commit", "post-merge")
CODEX_HOOKS_MARKER = "workscribe-managed hooks"
LEGACY_CODEX_HOOKS_MARKER = "workscribe-managed codex_hooks"
DEFAULT_GLOBAL_GIT_HOOKS_DIR = Path.home() / ".config" / "workscribe" / "git-hooks"
DEFAULT_GLOBAL_STATE_PATH = Path.home() / ".config" / "workscribe" / "global-state.json"
WORKSCRIBE_CODEX_HOOK_FRAGMENT = "-m workscribe hook codex"


def codex_hook_command() -> str:
    python = Path(sys.executable).resolve()
    prefix = pythonpath_prefix()
    return f'{prefix}"{python}" -m workscribe hook codex'


def git_hook_command(hook_name: str) -> str:
    python = Path(sys.executable).resolve()
    prefix = pythonpath_prefix()
    return f'{prefix}exec "{python}" -m workscribe hook git {hook_name} "$@"'


def install_codex_hooks(repo_root: Path) -> Path:
    codex_dir = repo_root / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    hooks_path = codex_dir / "hooks.json"
    data = read_json_file(hooks_path) if hooks_path.exists() else {"hooks": {}}
    if not isinstance(data, dict):
        raise WorkscribeError(f"Unexpected JSON shape in {hooks_path}")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise WorkscribeError(f"Unexpected hooks object in {hooks_path}")

    command = codex_hook_command()
    remove_lifecycle_hook_command_fragment(hooks, WORKSCRIBE_CODEX_HOOK_FRAGMENT)
    ensure_lifecycle_hook(
        hooks,
        "SessionStart",
        {
            "matcher": "startup|resume|clear",
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 30,
                    "statusMessage": "workscribe: recording session start",
                }
            ],
        },
    )
    ensure_lifecycle_hook(
        hooks,
        "UserPromptSubmit",
        {
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 30,
                }
            ],
        },
    )
    ensure_lifecycle_hook(
        hooks,
        "PostToolUse",
        {
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 30,
                    "statusMessage": "workscribe: logging tool activity",
                }
            ],
        },
    )
    write_json_file(hooks_path, data)
    return hooks_path


def uninstall_codex_hooks(repo_root: Path) -> Path | None:
    hooks_path = repo_root / ".codex" / "hooks.json"
    if not hooks_path.exists():
        return None
    data = read_json_file(hooks_path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return hooks_path
    empty_events = []
    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        retained_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                retained_entries.append(entry)
                continue
            hook_list = entry.get("hooks")
            if not isinstance(hook_list, list):
                retained_entries.append(entry)
                continue
            filtered = [
                hook
                for hook in hook_list
                if not (
                    isinstance(hook, dict)
                    and hook.get("type") == "command"
                    and WORKSCRIBE_CODEX_HOOK_FRAGMENT in str(hook.get("command", ""))
                )
            ]
            if filtered:
                entry["hooks"] = filtered
                retained_entries.append(entry)
        hooks[event_name] = retained_entries
        if not retained_entries:
            empty_events.append(event_name)
    for event_name in empty_events:
        hooks.pop(event_name, None)
    if not hooks:
        hooks_path.unlink()
        codex_dir = hooks_path.parent
        if codex_dir.exists() and not any(codex_dir.iterdir()):
            codex_dir.rmdir()
        return None
    write_json_file(hooks_path, data)
    return hooks_path


def install_git_hooks(repo_root: Path) -> list[Path]:
    hooks_dir = git_hooks_dir(repo_root)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    updated: list[Path] = []
    for hook_name in GIT_HOOKS:
        hook_path = hooks_dir / hook_name
        backup_path = hooks_dir / f"{hook_name}.workscribe.original"
        if hook_path.exists() and WORKSCRIBE_MARKER not in hook_path.read_text():
            shutil.move(str(hook_path), str(backup_path))
        hook_path.write_text(render_git_hook_script(hook_name, backup_path if backup_path.exists() else None))
        hook_path.chmod(0o755)
        updated.append(hook_path)
    return updated


def uninstall_git_hooks(repo_root: Path) -> list[Path]:
    hooks_dir = git_hooks_dir(repo_root)
    restored: list[Path] = []
    for hook_name in GIT_HOOKS:
        hook_path = hooks_dir / hook_name
        backup_path = hooks_dir / f"{hook_name}.workscribe.original"
        if hook_path.exists() and WORKSCRIBE_MARKER in hook_path.read_text():
            hook_path.unlink()
            if backup_path.exists():
                shutil.move(str(backup_path), str(hook_path))
                restored.append(hook_path)
        elif backup_path.exists():
            restored.append(backup_path)
    return restored


def render_git_hook_script(hook_name: str, backup_path: Path | None) -> str:
    backup_lines = ""
    if backup_path is not None:
        backup_lines = (
            f'if [ -x "{backup_path}" ]; then\n'
            f'  "{backup_path}" "$@"\n'
            "  backup_status=$?\n"
            "fi\n"
        )
    return (
        "#!/bin/sh\n"
        f"# {WORKSCRIBE_MARKER}\n"
        "backup_status=0\n"
        f"{backup_lines}"
        f"{git_hook_command(hook_name)}\n"
        "workscribe_status=$?\n"
        "if [ \"$backup_status\" -ne 0 ]; then\n"
        "  exit \"$backup_status\"\n"
        "fi\n"
        "exit \"$workscribe_status\"\n"
    )


def ensure_lifecycle_hook(hooks: dict[str, Any], event_name: str, new_entry: dict[str, Any]) -> None:
    entries = hooks.setdefault(event_name, [])
    if not isinstance(entries, list):
        raise WorkscribeError(f"Unexpected JSON shape for hook event {event_name}")
    commands = [
        hook.get("command")
        for entry in entries
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    ]
    new_commands = [
        hook.get("command")
        for hook in new_entry.get("hooks", [])
        if isinstance(hook, dict)
    ]
    if any(command in commands for command in new_commands):
        return
    entries.append(new_entry)


def remove_lifecycle_hook_command_fragment(hooks: dict[str, Any], command_fragment: str) -> None:
    empty_events = []
    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        retained_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                retained_entries.append(entry)
                continue
            hook_list = entry.get("hooks")
            if not isinstance(hook_list, list):
                retained_entries.append(entry)
                continue
            filtered = [
                hook
                for hook in hook_list
                if not (
                    isinstance(hook, dict)
                    and hook.get("type") == "command"
                    and command_fragment in str(hook.get("command", ""))
                )
            ]
            if filtered:
                entry["hooks"] = filtered
                retained_entries.append(entry)
        hooks[event_name] = retained_entries
        if not retained_entries:
            empty_events.append(event_name)
    for event_name in empty_events:
        hooks.pop(event_name, None)


def read_json_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise WorkscribeError(f"Expected JSON object in {path}")
    return data


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def find_repo_config_path(repo_root: Path) -> Path:
    return repo_root / ROOT_CONFIG_FILENAME


def git_dir(repo_root: Path) -> Path:
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        content = dot_git.read_text().strip()
        prefix = "gitdir:"
        if not content.lower().startswith(prefix):
            raise WorkscribeError(f"Unsupported .git file format in {dot_git}")
        return (repo_root / content[len(prefix) :].strip()).resolve()
    raise WorkscribeError(f"No .git directory found in {repo_root}")


def git_hooks_dir(repo_root: Path) -> Path:
    return git_dir(repo_root) / "hooks"


def discover_repositories(root: Path) -> list[Path]:
    repos: set[Path] = set()
    for dot_git in root.rglob(".git"):
        if dot_git.is_dir() or dot_git.is_file():
            repos.add(dot_git.parent.resolve())
    if (root / ".git").exists():
        repos.add(root.resolve())
    return sorted(repos)


def install_global_codex_hooks(codex_home: Path | None = None) -> tuple[Path, Path]:
    home = (codex_home or (Path.home() / ".codex")).resolve()
    home.mkdir(parents=True, exist_ok=True)
    config_path = home / "config.toml"
    hooks_path = home / "hooks.json"
    ensure_codex_hooks_feature_enabled(config_path)
    install_codex_hooks_in_dir(home)
    return config_path, hooks_path


def uninstall_global_codex_hooks(codex_home: Path | None = None) -> tuple[Path, Path | None]:
    home = (codex_home or (Path.home() / ".codex")).resolve()
    config_path = home / "config.toml"
    hooks_path = uninstall_codex_hooks_in_dir(home)
    disable_codex_hooks_feature_marker(config_path)
    return config_path, hooks_path


def install_global_git_hooks(hooks_dir: Path | None = None, state_path: Path | None = None) -> Path:
    target_dir = (hooks_dir or DEFAULT_GLOBAL_GIT_HOOKS_DIR).resolve()
    state_file = (state_path or DEFAULT_GLOBAL_STATE_PATH).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    previous = git_config_get_global("core.hooksPath")
    if previous != str(target_dir):
        write_global_state(state_file, {"previous_core_hooks_path": previous})
    for hook_name in GIT_HOOKS:
        hook_path = target_dir / hook_name
        hook_path.write_text(render_git_hook_script(hook_name, None))
        hook_path.chmod(0o755)
    git_config_set_global("core.hooksPath", str(target_dir))
    return target_dir


def uninstall_global_git_hooks(hooks_dir: Path | None = None, state_path: Path | None = None) -> tuple[Path, str | None]:
    target_dir = (hooks_dir or DEFAULT_GLOBAL_GIT_HOOKS_DIR).resolve()
    state_file = (state_path or DEFAULT_GLOBAL_STATE_PATH).resolve()
    current = git_config_get_global("core.hooksPath")
    previous = read_global_state(state_file).get("previous_core_hooks_path")
    if current == str(target_dir):
        if previous:
            git_config_set_global("core.hooksPath", previous)
        else:
            git_config_unset_global("core.hooksPath")
    if target_dir.exists():
        for hook_name in GIT_HOOKS:
            hook_path = target_dir / hook_name
            if hook_path.exists():
                hook_path.unlink()
        if not any(target_dir.iterdir()):
            target_dir.rmdir()
    if state_file.exists():
        state_file.unlink()
    return target_dir, previous


def install_codex_hooks_in_dir(codex_dir: Path) -> Path:
    codex_dir.mkdir(parents=True, exist_ok=True)
    hooks_path = codex_dir / "hooks.json"
    data = read_json_file(hooks_path) if hooks_path.exists() else {"hooks": {}}
    if not isinstance(data, dict):
        raise WorkscribeError(f"Unexpected JSON shape in {hooks_path}")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise WorkscribeError(f"Unexpected hooks object in {hooks_path}")

    command = codex_hook_command()
    remove_lifecycle_hook_command_fragment(hooks, WORKSCRIBE_CODEX_HOOK_FRAGMENT)
    ensure_lifecycle_hook(
        hooks,
        "SessionStart",
        {
            "matcher": "startup|resume|clear",
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 30,
                    "statusMessage": "workscribe: recording session start",
                }
            ],
        },
    )
    ensure_lifecycle_hook(
        hooks,
        "UserPromptSubmit",
        {
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 30,
                }
            ],
        },
    )
    ensure_lifecycle_hook(
        hooks,
        "PostToolUse",
        {
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 30,
                    "statusMessage": "workscribe: logging tool activity",
                }
            ],
        },
    )
    write_json_file(hooks_path, data)
    return hooks_path


def uninstall_codex_hooks_in_dir(codex_dir: Path) -> Path | None:
    hooks_path = codex_dir / "hooks.json"
    if not hooks_path.exists():
        return None
    data = read_json_file(hooks_path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return hooks_path
    empty_events = []
    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        retained_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                retained_entries.append(entry)
                continue
            hook_list = entry.get("hooks")
            if not isinstance(hook_list, list):
                retained_entries.append(entry)
                continue
            filtered = [
                hook
                for hook in hook_list
                if not (
                    isinstance(hook, dict)
                    and hook.get("type") == "command"
                    and WORKSCRIBE_CODEX_HOOK_FRAGMENT in str(hook.get("command", ""))
                )
            ]
            if filtered:
                entry["hooks"] = filtered
                retained_entries.append(entry)
        hooks[event_name] = retained_entries
        if not retained_entries:
            empty_events.append(event_name)
    for event_name in empty_events:
        hooks.pop(event_name, None)
    if not hooks:
        hooks_path.unlink()
        return None
    write_json_file(hooks_path, data)
    return hooks_path


def ensure_codex_hooks_feature_enabled(config_path: Path) -> None:
    if config_path.exists():
        lines = config_path.read_text().splitlines()
    else:
        lines = []

    lines = [line.replace(LEGACY_CODEX_HOOKS_MARKER, CODEX_HOOKS_MARKER) for line in lines]

    features_index = find_table_line(lines, "[features]")
    if features_index is not None:
        section_end = find_section_end(lines, features_index + 1)
        for index in range(features_index + 1, section_end):
            stripped = lines[index].strip()
            if stripped.startswith("hooks"):
                if "true" in stripped.lower():
                    config_path.write_text("\n".join(lines) + "\n")
                    return
                lines[index] = "hooks = true  # workscribe-managed override"
                config_path.write_text("\n".join(lines) + "\n")
                return
            if stripped.startswith("codex_hooks"):
                lines[index] = "hooks = true"
                config_path.write_text("\n".join(lines) + "\n")
                return
        lines.insert(section_end, f"hooks = true  # {CODEX_HOOKS_MARKER}")
        config_path.write_text("\n".join(lines) + "\n")
        return

    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(
        [
            f"# {CODEX_HOOKS_MARKER}:start",
            "[features]",
            "hooks = true",
            f"# {CODEX_HOOKS_MARKER}:end",
        ]
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines) + "\n")


def disable_codex_hooks_feature_marker(config_path: Path) -> None:
    if not config_path.exists():
        return
    lines = config_path.read_text().splitlines()
    filtered: list[str] = []
    in_marker = False
    for line in lines:
        if line.strip() in {f"# {CODEX_HOOKS_MARKER}:start", f"# {LEGACY_CODEX_HOOKS_MARKER}:start"}:
            in_marker = True
            continue
        if line.strip() in {f"# {CODEX_HOOKS_MARKER}:end", f"# {LEGACY_CODEX_HOOKS_MARKER}:end"}:
            in_marker = False
            continue
        stripped = line.strip()
        if in_marker and (stripped.startswith("hooks") or stripped.startswith("codex_hooks")):
            continue
        if CODEX_HOOKS_MARKER in line or LEGACY_CODEX_HOOKS_MARKER in line:
            continue
        filtered.append(line)
    config_path.write_text("\n".join(filtered).rstrip() + ("\n" if filtered else ""))


def find_table_line(lines: list[str], header: str) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == header:
            return index
    return None


def find_section_end(lines: list[str], start_index: int) -> int:
    for index in range(start_index, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return index
    return len(lines)


def pythonpath_prefix() -> str:
    src_root = Path(__file__).resolve().parents[2] / "src"
    if src_root.is_dir():
        return f'PYTHONPATH="{src_root}" '
    return ""


def git_config_get_global(key: str) -> str | None:
    completed = subprocess.run(
        ["git", "config", "--global", "--get", key],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def git_config_set_global(key: str, value: str) -> None:
    try:
        subprocess.run(["git", "config", "--global", key, value], check=True)
    except subprocess.CalledProcessError as exc:
        raise WorkscribeError(f"Failed to set global git config {key}: {exc}") from exc


def git_config_unset_global(key: str) -> None:
    subprocess.run(["git", "config", "--global", "--unset", key], check=False)


def write_global_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_global_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {}
