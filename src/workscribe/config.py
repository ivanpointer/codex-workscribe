from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


ROOT_CONFIG_FILENAME = ".codex-workscribe.toml"
ROOT_DB_FILENAME = ".codex-workscribe.sqlite"


class WorkscribeError(RuntimeError):
    """Base error for user-facing failures."""


@dataclass(slots=True)
class WorkspaceContext:
    start_dir: Path
    program_root: Path
    program_config_path: Path
    database_path: Path
    repo_override_path: Path | None
    effective_config: dict[str, Any]


def load_toml_file(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise WorkscribeError(f"Config file is not a TOML table: {path}")
    return data


def find_program_root(start_dir: Path) -> Path | None:
    for current in [start_dir, *start_dir.parents]:
        if (current / ROOT_CONFIG_FILENAME).is_file() and (current / ROOT_DB_FILENAME).is_file():
            return current
    return None


def find_git_root(start_dir: Path) -> Path | None:
    for current in [start_dir, *start_dir.parents]:
        if (current / ".git").exists():
            return current
    return None


def find_repo_override(start_dir: Path, program_root: Path) -> Path | None:
    for current in [start_dir, *start_dir.parents]:
        if current == program_root:
            return None
        candidate = current / ROOT_CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def discover_workspace(start_dir: Path | None = None) -> WorkspaceContext:
    resolved_start = (start_dir or Path.cwd()).resolve()
    program_root = find_program_root(resolved_start)
    if program_root is None:
        raise WorkscribeError(
            "No workscribe root found. Walked parent directories looking for both "
            f"{ROOT_CONFIG_FILENAME} and {ROOT_DB_FILENAME}. Run `workscribe init program` first."
        )

    program_config_path = program_root / ROOT_CONFIG_FILENAME
    database_path = program_root / ROOT_DB_FILENAME
    repo_override_path = find_repo_override(resolved_start, program_root)

    config = load_toml_file(program_config_path)
    if repo_override_path is not None:
        repo_config = load_toml_file(repo_override_path)
        config = deep_merge(config, repo_config)

    return WorkspaceContext(
        start_dir=resolved_start,
        program_root=program_root,
        program_config_path=program_config_path,
        database_path=database_path,
        repo_override_path=repo_override_path,
        effective_config=config,
    )


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def format_program_config(
    *,
    client_key: str,
    client_name: str,
    billing_mode: str,
    default_hourly_rate: float | None,
    currency: str,
    program_name: str,
    timezone: str,
) -> str:
    rate_line = (
        f"default_hourly_rate = {int(default_hourly_rate) if float(default_hourly_rate).is_integer() else default_hourly_rate}\n"
        if default_hourly_rate is not None
        else ""
    )
    return (
        f'client_key = "{client_key}"\n'
        f'client_name = "{client_name}"\n'
        f'billing_mode = "{billing_mode}"\n'
        f"{rate_line}"
        f'currency = "{currency}"\n'
        f'program_name = "{program_name}"\n\n'
        "[reporting]\n"
        f'timezone = "{timezone}"\n\n'
        "[traditional_estimation]\n"
        "enabled = true\n"
        'default_confidence = "medium"\n'
    )


def format_repo_config(
    *,
    project_key: str,
    project_name: str,
    project_code: str | None,
    tags: list[str],
) -> str:
    code_line = f'project_code = "{project_code}"\n' if project_code else ""
    tags_literal = ", ".join(f'"{tag}"' for tag in tags)
    return (
        f'project_key = "{project_key}"\n'
        f'project_name = "{project_name}"\n'
        f"{code_line}"
        f"tags = [{tags_literal}]\n"
    )


def default_client_key(path: Path) -> str:
    return slugify(path.name)


def default_project_key(path: Path) -> str:
    return slugify(path.name)


def slugify(value: str) -> str:
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {" ", "-", "_", "."}:
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "workscribe"


def current_timezone() -> str:
    return os.environ.get("TZ", "UTC")
