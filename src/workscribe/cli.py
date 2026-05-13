from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path

from workscribe import __version__
from workscribe.config import (
    ROOT_CONFIG_FILENAME,
    ROOT_DB_FILENAME,
    WorkscribeError,
    current_timezone,
    default_client_key,
    default_project_key,
    discover_workspace,
    ensure_parent,
    find_git_root,
    find_program_root,
    format_program_config,
    format_repo_config,
    slugify,
)
from workscribe.db import (
    connect_database,
    finalize_session,
    find_active_session,
    find_latest_session,
    find_session_by_key,
    initialize_database,
    insert_note,
    record_installation,
    utc_now,
)
from workscribe.explorer.server import run_explorer
from workscribe.hooks import handle_codex_hook, handle_git_hook, sync_metadata
from workscribe.install import (
    DEFAULT_GLOBAL_GIT_HOOKS_DIR,
    DEFAULT_GLOBAL_STATE_PATH,
    discover_repositories,
    find_repo_config_path,
    install_codex_hooks,
    install_global_codex_hooks,
    install_global_git_hooks,
    install_git_hooks,
    uninstall_codex_hooks,
    uninstall_global_codex_hooks,
    uninstall_global_git_hooks,
    uninstall_git_hooks,
)
from workscribe.reporting import (
    build_report_payload,
    fetch_report_data,
    fetch_program_report_data,
    parse_report_window,
    persist_report,
    write_report_artifacts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workscribe")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize workscribe metadata and storage")
    init_subparsers = init_parser.add_subparsers(dest="init_scope", required=True)

    init_program = init_subparsers.add_parser("program", help="Create a workscribe program root")
    init_program.add_argument("--path", type=Path, default=Path.cwd())
    init_program.add_argument("--client-key")
    init_program.add_argument("--client-name")
    init_program.add_argument("--program-name")
    init_program.add_argument("--billing-mode", default="time_and_materials")
    init_program.add_argument("--hourly-rate", type=float)
    init_program.add_argument("--currency", default="USD")
    init_program.add_argument("--timezone", default=current_timezone())
    init_program.add_argument("--force", action="store_true")
    init_program.set_defaults(func=cmd_init_program)

    init_repo = init_subparsers.add_parser("repo", help="Create repo-local workscribe metadata")
    init_repo.add_argument("--path", type=Path, default=Path.cwd())
    init_repo.add_argument("--project-key")
    init_repo.add_argument("--project-name")
    init_repo.add_argument("--project-code")
    init_repo.add_argument("--tags", nargs="*", default=[])
    init_repo.add_argument("--force", action="store_true")
    init_repo.set_defaults(func=cmd_init_repo)

    init_project = init_subparsers.add_parser("project", help="Alias for repo-local project metadata")
    init_project.add_argument("--path", type=Path, default=Path.cwd())
    init_project.add_argument("--project-key")
    init_project.add_argument("--project-name")
    init_project.add_argument("--project-code")
    init_project.add_argument("--tags", nargs="*", default=[])
    init_project.add_argument("--force", action="store_true")
    init_project.set_defaults(func=cmd_init_repo)

    install_parser = subparsers.add_parser("install", help="Install Codex and Git hook wiring")
    install_parser.add_argument("--repo", type=Path, default=Path.cwd())
    install_parser.add_argument("--all-repos", action="store_true")
    install_parser.add_argument("--skip-codex", action="store_true")
    install_parser.add_argument("--skip-git", action="store_true")
    install_parser.set_defaults(func=cmd_install)

    install_global_parser = subparsers.add_parser("install-global", help="Install global Codex and Git hooks")
    install_global_parser.add_argument("--skip-codex", action="store_true")
    install_global_parser.add_argument("--skip-git", action="store_true")
    install_global_parser.add_argument("--codex-home", type=Path)
    install_global_parser.add_argument("--git-hooks-dir", type=Path, default=DEFAULT_GLOBAL_GIT_HOOKS_DIR)
    install_global_parser.add_argument("--git-state-path", type=Path, default=DEFAULT_GLOBAL_STATE_PATH)
    install_global_parser.set_defaults(func=cmd_install_global)

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove Codex and Git hook wiring")
    uninstall_parser.add_argument("--repo", type=Path, default=Path.cwd())
    uninstall_parser.add_argument("--all-repos", action="store_true")
    uninstall_parser.add_argument("--skip-codex", action="store_true")
    uninstall_parser.add_argument("--skip-git", action="store_true")
    uninstall_parser.set_defaults(func=cmd_uninstall)

    uninstall_global_parser = subparsers.add_parser("uninstall-global", help="Remove global Codex and Git hooks")
    uninstall_global_parser.add_argument("--skip-codex", action="store_true")
    uninstall_global_parser.add_argument("--skip-git", action="store_true")
    uninstall_global_parser.add_argument("--codex-home", type=Path)
    uninstall_global_parser.add_argument("--git-hooks-dir", type=Path, default=DEFAULT_GLOBAL_GIT_HOOKS_DIR)
    uninstall_global_parser.add_argument("--git-state-path", type=Path, default=DEFAULT_GLOBAL_STATE_PATH)
    uninstall_global_parser.set_defaults(func=cmd_uninstall_global)

    note_parser = subparsers.add_parser("note", help="Add a manual note to the telemetry ledger")
    note_parser.add_argument("text", nargs="*")
    note_parser.add_argument("--path", type=Path, default=Path.cwd())
    note_parser.add_argument("--session-key")
    note_parser.add_argument("--type", default="note")
    note_parser.set_defaults(func=cmd_note)

    end_parser = subparsers.add_parser("end-session", help="Add a session summary and close the active session")
    end_parser.add_argument("text", nargs="*")
    end_parser.add_argument("--path", type=Path, default=Path.cwd())
    end_parser.add_argument("--session-key")
    end_parser.add_argument("--type", default="session_end")
    end_parser.add_argument("--keep-open", action="store_true")
    end_parser.set_defaults(func=cmd_end_session)

    report_parser = subparsers.add_parser("report", help="Generate a report bundle for a date range")
    report_parser.add_argument("--path", type=Path, default=Path.cwd())
    report_parser.add_argument("--from", dest="date_from")
    report_parser.add_argument("--to", dest="date_to")
    report_parser.add_argument("--days", type=int, default=7)
    report_parser.add_argument("--scope", choices=["project", "program"], default="project")
    report_parser.add_argument("--output-dir", type=Path)
    report_parser.set_defaults(func=cmd_report)

    explore_parser = subparsers.add_parser("explore", help="Launch a local read-only SQLite data explorer")
    explore_parser.add_argument("--path", type=Path, default=Path.cwd())
    explore_parser.add_argument("--host", default="127.0.0.1")
    explore_parser.add_argument("--port", type=int, default=0)
    explore_parser.add_argument("--open", dest="open_browser", action="store_true", default=True)
    explore_parser.add_argument("--no-open", dest="open_browser", action="store_false")
    explore_parser.set_defaults(func=cmd_explore)

    status_parser = subparsers.add_parser("status", help="Show resolved workscribe context")
    status_parser.add_argument("--path", type=Path, default=Path.cwd())
    status_parser.set_defaults(func=cmd_status)

    hook_parser = subparsers.add_parser("hook", help=argparse.SUPPRESS)
    hook_subparsers = hook_parser.add_subparsers(dest="hook_kind", required=True)
    hook_codex = hook_subparsers.add_parser("codex", help=argparse.SUPPRESS)
    hook_codex.set_defaults(func=cmd_hook_codex)
    hook_git = hook_subparsers.add_parser("git", help=argparse.SUPPRESS)
    hook_git.add_argument("hook_name", choices=["post-commit", "post-merge"])
    hook_git.set_defaults(func=cmd_hook_git)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except WorkscribeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def cmd_init_program(args: argparse.Namespace) -> int:
    root = args.path.resolve()
    config_path = root / ROOT_CONFIG_FILENAME
    database_path = root / ROOT_DB_FILENAME

    if find_program_root(root) and not args.force:
        raise WorkscribeError(f"A workscribe root already exists at or above {root}")
    if config_path.exists() and not args.force:
        raise WorkscribeError(f"Config already exists: {config_path}")

    root.mkdir(parents=True, exist_ok=True)
    client_key = args.client_key or default_client_key(root)
    client_name = args.client_name or root.name
    program_name = args.program_name or root.name
    config_text = format_program_config(
        client_key=slugify(client_key),
        client_name=client_name,
        billing_mode=args.billing_mode,
        default_hourly_rate=args.hourly_rate,
        currency=args.currency,
        program_name=program_name,
        timezone=args.timezone,
    )
    config_path.write_text(config_text)
    with connect_database(database_path) as conn:
        initialize_database(conn)
    print(f"Initialized workscribe program root at {root}")
    print(f"  config: {config_path}")
    print(f"  database: {database_path}")
    return 0


def cmd_init_repo(args: argparse.Namespace) -> int:
    path = args.path.resolve()
    repo_root = find_git_root(path) or path
    config_path = find_repo_config_path(repo_root)

    if config_path.exists() and not args.force:
        raise WorkscribeError(f"Repo config already exists: {config_path}")

    project_key = slugify(args.project_key or default_project_key(repo_root))
    project_name = args.project_name or repo_root.name
    config_text = format_repo_config(
        project_key=project_key,
        project_name=project_name,
        project_code=args.project_code,
        tags=[str(tag) for tag in args.tags],
    )
    ensure_parent(config_path)
    config_path.write_text(config_text)
    print(f"Initialized workscribe repo config at {config_path}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    target_root = args.repo.resolve()
    workspace = discover_workspace(target_root)
    repo_roots = discover_repositories(target_root) if args.all_repos else [find_git_root(target_root) or target_root]
    installed_repos: list[tuple[Path, Path | None, list[Path]]] = []

    for repo_root in repo_roots:
        codex_path = None
        git_paths: list[Path] = []
        if not args.skip_codex:
            codex_path = install_codex_hooks(repo_root)
        if not args.skip_git:
            git_paths = install_git_hooks(repo_root)
        installed_repos.append((repo_root, codex_path, git_paths))

    with connect_database(workspace.database_path) as conn:
        initialize_database(conn)
        for repo_root, codex_path, git_paths in installed_repos:
            record_installation(
                conn,
                program_root=str(workspace.program_root),
                repo_root=str(repo_root),
                install_scope="repo",
                codex_hooks_enabled=not args.skip_codex,
                git_hooks_enabled=not args.skip_git,
                notes={
                    "codex_hooks_path": str(codex_path) if codex_path else None,
                    "git_hooks": [str(path) for path in git_paths],
                },
            )

    print(f"Installed workscribe hooks for {len(installed_repos)} repo(s)")
    for repo_root, codex_path, git_paths in installed_repos:
        print(f"  repo:  {repo_root}")
        if codex_path:
            print(f"    codex: {codex_path}")
        for path in git_paths:
            print(f"    git:   {path}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    target_root = args.repo.resolve()
    workspace = discover_workspace(target_root)
    repo_roots = discover_repositories(target_root) if args.all_repos else [find_git_root(target_root) or target_root]
    removed_repos: list[tuple[Path, Path | None, list[Path]]] = []

    for repo_root in repo_roots:
        codex_path = None
        git_paths: list[Path] = []
        if not args.skip_codex:
            codex_path = uninstall_codex_hooks(repo_root)
        if not args.skip_git:
            git_paths = uninstall_git_hooks(repo_root)
        removed_repos.append((repo_root, codex_path, git_paths))

    with connect_database(workspace.database_path) as conn:
        initialize_database(conn)
        for repo_root, codex_path, git_paths in removed_repos:
            record_installation(
                conn,
                program_root=str(workspace.program_root),
                repo_root=str(repo_root),
                install_scope="repo-uninstall",
                codex_hooks_enabled=False,
                git_hooks_enabled=False,
                notes={
                    "codex_hooks_path": str(codex_path) if codex_path else None,
                    "git_hooks": [str(path) for path in git_paths],
                },
            )

    print(f"Uninstalled workscribe-managed hooks for {len(removed_repos)} repo(s)")
    return 0


def cmd_install_global(args: argparse.Namespace) -> int:
    codex_result = None
    git_result = None
    if not args.skip_codex:
        codex_result = install_global_codex_hooks(args.codex_home)
    if not args.skip_git:
        git_result = install_global_git_hooks(args.git_hooks_dir, args.git_state_path)
    print("Installed global workscribe hooks")
    if codex_result:
        config_path, hooks_path = codex_result
        print(f"  codex config: {config_path}")
        print(f"  codex hooks:  {hooks_path}")
    if git_result:
        print(f"  git hooks:    {git_result}")
    return 0


def cmd_uninstall_global(args: argparse.Namespace) -> int:
    codex_result = None
    git_result = None
    if not args.skip_codex:
        codex_result = uninstall_global_codex_hooks(args.codex_home)
    if not args.skip_git:
        git_result = uninstall_global_git_hooks(args.git_hooks_dir, args.git_state_path)
    print("Uninstalled global workscribe hooks")
    if codex_result:
        config_path, hooks_path = codex_result
        print(f"  codex config: {config_path}")
        print(f"  codex hooks:  {hooks_path}")
    if git_result:
        hooks_dir, previous = git_result
        print(f"  git hooks:    {hooks_dir}")
        print(f"  restored core.hooksPath: {previous}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    workspace = discover_workspace(args.path.resolve())
    print(f"program_root={workspace.program_root}")
    print(f"program_config={workspace.program_config_path}")
    print(f"database={workspace.database_path}")
    print(f"repo_override={workspace.repo_override_path}")
    print(f"client_key={workspace.effective_config.get('client_key')}")
    print(f"project_key={workspace.effective_config.get('project_key')}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    content = collect_text(args.text)
    workspace = discover_workspace(args.path.resolve())
    with connect_database(workspace.database_path) as conn:
        initialize_database(conn)
        metadata = sync_metadata(conn, workspace, args.path.resolve())
        session = resolve_note_session(conn, metadata.project_id, args.session_key)
        insert_note(
            conn,
            project_id=metadata.project_id,
            session_id=int(session["id"]) if session else None,
            note_type=args.type,
            content=content,
            metadata={
                "cwd": str(args.path.resolve()),
                "session_key": session["session_key"] if session else None,
            },
        )
    print(f"Recorded {args.type} note")
    return 0


def cmd_end_session(args: argparse.Namespace) -> int:
    content = collect_text(args.text, allow_empty=True) or "Session ended."
    workspace = discover_workspace(args.path.resolve())
    with connect_database(workspace.database_path) as conn:
        initialize_database(conn)
        metadata = sync_metadata(conn, workspace, args.path.resolve())
        session = resolve_end_session(conn, metadata.project_id, args.session_key)
        if session is None:
            raise WorkscribeError("No session found to annotate or close.")

        insert_note(
            conn,
            project_id=metadata.project_id,
            session_id=int(session["id"]),
            note_type=args.type,
            content=content,
            metadata={
                "cwd": str(args.path.resolve()),
                "session_key": session["session_key"],
                "status_before": session["status"],
            },
        )
        if session["status"] == "active" and not args.keep_open:
            finalize_session(conn, session_key=str(session["session_key"]), ended_at=utc_now())
            print(f"Recorded session summary and closed {session['session_key']}")
        else:
            print(f"Recorded session summary for {session['session_key']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    anchor = args.path.resolve()
    workspace = discover_workspace(anchor)
    try:
        window = parse_report_window(start_text=args.date_from, end_text=args.date_to, days=args.days)
    except ValueError as exc:
        raise WorkscribeError(str(exc)) from exc
    with connect_database(workspace.database_path) as conn:
        initialize_database(conn)
        metadata = sync_metadata(conn, workspace, anchor)
        if args.scope == "program":
            try:
                raw_data = fetch_program_report_data(conn, str(workspace.program_root), window)
            except ValueError as exc:
                raise WorkscribeError(str(exc)) from exc
        else:
            raw_data = fetch_report_data(conn, metadata.project_id, window)
        payload = build_report_payload(raw_data)
        output_dir = args.output_dir or default_report_output_dir(workspace.program_root, payload)
        artifacts = write_report_artifacts(payload, output_dir)
        persist_report(
            conn,
            project_id=metadata.project_id,
            payload=payload,
            report_markdown=artifacts.markdown_path.read_text(),
        )
    print(f"Generated report bundle at {artifacts.output_dir}")
    print(f"  markdown: {artifacts.markdown_path}")
    print(f"  json:     {artifacts.json_path}")
    print(f"  csv:      {artifacts.csv_path}")
    print(f"  charts:   {artifacts.activity_svg_path.name}, {artifacts.evidence_svg_path.name}")
    return 0


def cmd_explore(args: argparse.Namespace) -> int:
    validate_explorer_host(args.host)
    workspace = discover_workspace(args.path.resolve())
    run_explorer(workspace, host=args.host, port=args.port, open_browser=args.open_browser)
    return 0


def validate_explorer_host(host: str) -> None:
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise WorkscribeError("The explorer is local-only; --host must be localhost or a loopback address.")


def cmd_hook_codex(args: argparse.Namespace) -> int:
    return handle_codex_hook(sys.stdin.read())


def cmd_hook_git(args: argparse.Namespace) -> int:
    return handle_git_hook(args.hook_name)


def resolve_note_session(conn, project_id: int, session_key: str | None):
    if session_key:
        session = find_session_by_key(conn, session_key)
        if session is None:
            raise WorkscribeError(f"Unknown session: {session_key}")
        return session
    return find_active_session(conn, project_id) or find_latest_session(conn, project_id)


def resolve_end_session(conn, project_id: int, session_key: str | None):
    if session_key:
        session = find_session_by_key(conn, session_key)
        if session is None:
            raise WorkscribeError(f"Unknown session: {session_key}")
        return session
    return find_active_session(conn, project_id) or find_latest_session(conn, project_id)


def collect_text(parts: list[str], *, allow_empty: bool = False) -> str:
    if parts:
        return " ".join(parts).strip()
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            return piped
    if allow_empty:
        return ""
    raise WorkscribeError("Note text is required. Pass it as arguments or pipe it on stdin.")


def default_report_output_dir(program_root: Path, payload: dict) -> Path:
    project_key = str(payload["project"]["project_key"])
    start_day = str(payload["window"]["start"])[:10]
    end_day = str(payload["window"]["end"])[:10]
    return program_root / "reports" / project_key / f"{start_day}_to_{end_day}"
