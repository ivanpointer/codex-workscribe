from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from workscribe.db import utc_now


@dataclass(slots=True)
class ReportWindow:
    start: datetime
    end: datetime


@dataclass(slots=True)
class ReportArtifacts:
    output_dir: Path
    markdown_path: Path
    json_path: Path
    csv_path: Path
    activity_svg_path: Path
    evidence_svg_path: Path


def parse_report_window(
    *, start_text: str | None, end_text: str | None, days: int | None, now: datetime | None = None
) -> ReportWindow:
    current = now or datetime.now(timezone.utc)
    if start_text:
        start_day = date.fromisoformat(start_text)
    elif days:
        start_day = (current - timedelta(days=max(days - 1, 0))).date()
    else:
        start_day = current.date()

    if end_text:
        end_day = date.fromisoformat(end_text)
    else:
        end_day = current.date()

    start_dt = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_day, time.max, tzinfo=timezone.utc)
    if end_dt < start_dt:
        raise ValueError("Report end date must not be earlier than start date.")
    return ReportWindow(start=start_dt, end=end_dt)


def fetch_report_data(conn: sqlite3.Connection, project_id: int, window: ReportWindow) -> dict[str, Any]:
    params = {"project_id": project_id, "start": window.start.isoformat(), "end": window.end.isoformat()}
    project = dict(
        conn.execute(
            """
            SELECT p.*, c.client_key, c.name AS client_name, c.currency, c.default_hourly_rate
            FROM projects p
            JOIN clients c ON c.id = p.client_id
            WHERE p.id = :project_id
            """,
            params,
        ).fetchone()
    )
    sessions = [
        dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM sessions
            WHERE project_id = :project_id
              AND COALESCE(ended_at, started_at, created_at) BETWEEN :start AND :end
            ORDER BY COALESCE(started_at, created_at)
            """,
            params,
        ).fetchall()
    ]
    notes = [
        dict(row)
        for row in conn.execute(
            """
            SELECT n.*, s.session_key
            FROM notes n
            LEFT JOIN sessions s ON s.id = n.session_id
            WHERE n.project_id = :project_id
              AND n.created_at BETWEEN :start AND :end
            ORDER BY n.created_at
            """,
            params,
        ).fetchall()
    ]
    commits = [
        dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM commits
            WHERE project_id = :project_id
              AND committed_at BETWEEN :start AND :end
            ORDER BY committed_at
            """,
            params,
        ).fetchall()
    ]
    prompts = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM prompts p
        JOIN sessions s ON s.id = p.session_id
        WHERE s.project_id = :project_id
          AND p.submitted_at BETWEEN :start AND :end
        """,
        params,
    ).fetchone()["count"]
    tool_events = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM tool_events t
        JOIN sessions s ON s.id = t.session_id
        WHERE s.project_id = :project_id
          AND t.captured_at BETWEEN :start AND :end
        """,
        params,
    ).fetchone()["count"]

    return {
        "project": project,
        "scope": "project",
        "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "sessions": sessions,
        "notes": notes,
        "commits": commits,
        "prompts_count": int(prompts or 0),
        "tool_events_count": int(tool_events or 0),
    }


def fetch_program_report_data(conn: sqlite3.Connection, program_root: str, window: ReportWindow) -> dict[str, Any]:
    params = {"program_root": program_root, "start": window.start.isoformat(), "end": window.end.isoformat()}
    project_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.*, c.client_key, c.name AS client_name, c.currency, c.default_hourly_rate
            FROM projects p
            JOIN clients c ON c.id = p.client_id
            WHERE p.program_root = :program_root
            ORDER BY p.project_key
            """,
            params,
        ).fetchall()
    ]
    if not project_rows:
        raise ValueError(f"No tracked projects found for program root {program_root}")

    sessions = [
        dict(row)
        for row in conn.execute(
            """
            SELECT s.*, p.project_key, p.name AS project_name
            FROM sessions s
            JOIN projects p ON p.id = s.project_id
            WHERE p.program_root = :program_root
              AND COALESCE(s.ended_at, s.started_at, s.created_at) BETWEEN :start AND :end
            ORDER BY COALESCE(s.started_at, s.created_at)
            """,
            params,
        ).fetchall()
    ]
    notes = [
        dict(row)
        for row in conn.execute(
            """
            SELECT n.*, s.session_key, p.project_key, p.name AS project_name
            FROM notes n
            JOIN projects p ON p.id = n.project_id
            LEFT JOIN sessions s ON s.id = n.session_id
            WHERE p.program_root = :program_root
              AND n.created_at BETWEEN :start AND :end
            ORDER BY n.created_at
            """,
            params,
        ).fetchall()
    ]
    commits = [
        dict(row)
        for row in conn.execute(
            """
            SELECT c.*, p.project_key, p.name AS project_name
            FROM commits c
            JOIN projects p ON p.id = c.project_id
            WHERE p.program_root = :program_root
              AND c.committed_at BETWEEN :start AND :end
            ORDER BY c.committed_at
            """,
            params,
        ).fetchall()
    ]
    prompts = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM prompts pmt
        JOIN sessions s ON s.id = pmt.session_id
        JOIN projects p ON p.id = s.project_id
        WHERE p.program_root = :program_root
          AND pmt.submitted_at BETWEEN :start AND :end
        """,
        params,
    ).fetchone()["count"]
    tool_events = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM tool_events t
        JOIN sessions s ON s.id = t.session_id
        JOIN projects p ON p.id = s.project_id
        WHERE p.program_root = :program_root
          AND t.captured_at BETWEEN :start AND :end
        """,
        params,
    ).fetchone()["count"]

    representative = {
        "id": None,
        "project_key": "program",
        "name": Path(program_root).name,
        "client_name": project_rows[0]["client_name"],
        "client_key": project_rows[0]["client_key"],
        "currency": project_rows[0]["currency"],
        "default_hourly_rate": project_rows[0]["default_hourly_rate"],
        "program_root": program_root,
        "project_count": len(project_rows),
        "project_keys": [row["project_key"] for row in project_rows],
    }

    return {
        "project": representative,
        "scope": "program",
        "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "sessions": sessions,
        "notes": notes,
        "commits": commits,
        "prompts_count": int(prompts or 0),
        "tool_events_count": int(tool_events or 0),
    }


def build_report_payload(data: dict[str, Any]) -> dict[str, Any]:
    sessions = data["sessions"]
    notes = data["notes"]
    commits = data["commits"]

    total_elapsed_seconds = sum(int(session["elapsed_seconds"] or 0) for session in sessions)
    stopped_sessions = sum(1 for session in sessions if session["status"] == "stopped")
    files_changed = set()
    insertions = 0
    deletions = 0
    for commit in commits:
        changed_files = json.loads(commit["changed_files_json"] or "[]")
        files_changed.update(changed_files)
        insertions += int(commit["insertions"] or 0)
        deletions += int(commit["deletions"] or 0)

    note_type_counts = Counter(note["note_type"] for note in notes)
    daily_activity_minutes = summarize_daily_activity_minutes(sessions, notes, commits)
    highlights = collect_highlights(notes, commits)

    payload = {
        "project": data["project"],
        "scope": data.get("scope", "project"),
        "window": data["window"],
        "summary": {
            "session_count": len(sessions),
            "stopped_session_count": stopped_sessions,
            "elapsed_hours": round(total_elapsed_seconds / 3600, 2),
            "note_count": len(notes),
            "commit_count": len(commits),
            "file_count": len(files_changed),
            "insertions": insertions,
            "deletions": deletions,
            "prompt_count": data["prompts_count"],
            "tool_event_count": data["tool_events_count"],
        },
        "metrics": {
            "daily_activity_minutes": daily_activity_minutes,
            "note_type_counts": dict(note_type_counts),
        },
        "highlights": highlights,
        "sessions": sessions,
        "notes": notes,
        "commits": commits,
    }
    return payload


def summarize_daily_activity_minutes(
    sessions: list[dict[str, Any]], notes: list[dict[str, Any]], commits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    totals: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"elapsed_minutes": 0, "commits": 0, "notes": 0})
    for session in sessions:
        stamp = session.get("started_at") or session.get("created_at")
        if not stamp:
            continue
        day = datetime.fromisoformat(stamp).date().isoformat()
        totals[day]["elapsed_minutes"] += round(int(session.get("elapsed_seconds") or 0) / 60)
    for note in notes:
        day = datetime.fromisoformat(note["created_at"]).date().isoformat()
        totals[day]["notes"] += 1
    for commit in commits:
        day = datetime.fromisoformat(commit["committed_at"]).date().isoformat()
        totals[day]["commits"] += 1
    return [{"day": day, **totals[day]} for day in sorted(totals)]


def collect_highlights(notes: list[dict[str, Any]], commits: list[dict[str, Any]]) -> list[str]:
    highlights: list[str] = []
    for note in notes:
        summary = note.get("content_summary")
        if summary:
            highlights.append(str(summary))
    for commit in commits:
        subject = commit.get("subject")
        if subject:
            highlights.append(f"Commit: {subject}")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in highlights:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:12]


def write_report_artifacts(payload: dict[str, Any], output_dir: Path) -> ReportArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "report.md"
    json_path = output_dir / "report.json"
    csv_path = output_dir / "ledger.csv"
    activity_svg_path = output_dir / "activity-by-day.svg"
    evidence_svg_path = output_dir / "work-evidence.svg"

    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    csv_rows = build_ledger_rows(payload)
    write_csv(csv_path, csv_rows)
    activity_svg_path.write_text(render_daily_activity_svg(payload))
    evidence_svg_path.write_text(render_evidence_svg(payload))
    markdown_path.write_text(render_markdown_report(payload, activity_svg_path.name, evidence_svg_path.name))

    return ReportArtifacts(
        output_dir=output_dir,
        markdown_path=markdown_path,
        json_path=json_path,
        csv_path=csv_path,
        activity_svg_path=activity_svg_path,
        evidence_svg_path=evidence_svg_path,
    )


def build_ledger_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session in payload["sessions"]:
        rows.append(
            {
                "entry_type": "session",
                "timestamp": session.get("started_at") or session.get("created_at"),
                "project_key": session.get("project_key") or payload["project"].get("project_key") or "",
                "session_key": session.get("session_key"),
                "status": session.get("status"),
                "summary": "",
                "hours": round(int(session.get("elapsed_seconds") or 0) / 3600, 2),
                "commit_sha": "",
                "note_type": "",
            }
        )
    for note in payload["notes"]:
        rows.append(
            {
                "entry_type": "note",
                "timestamp": note.get("created_at"),
                "project_key": note.get("project_key") or payload["project"].get("project_key") or "",
                "session_key": note.get("session_key") or "",
                "status": "",
                "summary": note.get("content_summary") or note.get("content") or "",
                "hours": "",
                "commit_sha": "",
                "note_type": note.get("note_type") or "",
            }
        )
    for commit in payload["commits"]:
        rows.append(
            {
                "entry_type": "commit",
                "timestamp": commit.get("committed_at"),
                "project_key": commit.get("project_key") or payload["project"].get("project_key") or "",
                "session_key": "",
                "status": "",
                "summary": commit.get("subject") or "",
                "hours": "",
                "commit_sha": commit.get("commit_sha") or "",
                "note_type": "",
            }
        )
    rows.sort(key=lambda row: row["timestamp"] or "")
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "entry_type",
        "timestamp",
        "project_key",
        "session_key",
        "status",
        "summary",
        "hours",
        "commit_sha",
        "note_type",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render_markdown_report(payload: dict[str, Any], activity_chart_name: str, evidence_chart_name: str) -> str:
    project = payload["project"]
    summary = payload["summary"]
    highlights = payload["highlights"]
    note_counts = payload["metrics"]["note_type_counts"]
    top_note_types = ", ".join(f"{key}: {value}" for key, value in sorted(note_counts.items())) or "none"
    scope = payload.get("scope", "project")
    scope_label = "Program" if scope == "program" else "Project"
    lines = [
        f"# Work Report: {project['name']}",
        "",
        f"- Client: {project['client_name']}",
        f"- Scope: {scope_label}",
        f"- Window: {payload['window']['start'][:10]} to {payload['window']['end'][:10]}",
        f"- Sessions tracked: {summary['session_count']}",
        f"- Elapsed tracked hours: {summary['elapsed_hours']}",
        f"- Commits: {summary['commit_count']}",
        f"- Files changed: {summary['file_count']}",
        f"- Notes: {summary['note_count']}",
        f"- Prompts logged: {summary['prompt_count']}",
        f"- Tool events logged: {summary['tool_event_count']}",
        "",
    ]
    if scope == "program":
        project_keys = ", ".join(project.get("project_keys", []))
        lines.extend(
            [
                f"- Projects included: {project.get('project_count', 0)}",
                f"- Project keys: {project_keys or 'none'}",
                "",
            ]
        )
    lines.extend(
        [
            "## Visuals",
            "",
            f"![Activity by day]({activity_chart_name})",
            "",
            f"![Work evidence]({evidence_chart_name})",
            "",
            "## Highlights",
            "",
        ]
    )
    if highlights:
        lines.extend(f"- {item}" for item in highlights)
    else:
        lines.append("- No notable highlights were captured in notes or commit subjects for this period.")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            f"- Note types captured: {top_note_types}",
            f"- Net code churn: +{summary['insertions']} / -{summary['deletions']}",
            "- Use elapsed tracked hours as observed telemetry, not as a claim of perfect billable precision.",
            "- Client-facing value should be interpreted primarily from highlights, deliverables, and decisions.",
            "",
            f"_Generated at {utc_now()}_",
            "",
        ]
    )
    return "\n".join(lines)


def render_daily_activity_svg(payload: dict[str, Any]) -> str:
    rows = payload["metrics"]["daily_activity_minutes"]
    if not rows:
        rows = [{"day": payload["window"]["start"][:10], "elapsed_minutes": 0, "commits": 0, "notes": 0}]
    width = 760
    height = 320
    chart_left = 70
    chart_bottom = 260
    chart_width = 640
    chart_height = 180
    max_minutes = max(max(row["elapsed_minutes"], 1) for row in rows)
    bar_gap = 18
    bar_width = max(24, int((chart_width - bar_gap * (len(rows) - 1)) / max(len(rows), 1)))
    bars = []
    labels = []
    for index, row in enumerate(rows):
        x = chart_left + index * (bar_width + bar_gap)
        bar_height = int((row["elapsed_minutes"] / max_minutes) * chart_height) if max_minutes else 0
        y = chart_bottom - bar_height
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" rx="8" fill="#1f6feb" />'
            f'<text x="{x + bar_width / 2}" y="{y - 8}" font-size="12" text-anchor="middle" fill="#0f172a">{row["elapsed_minutes"]}m</text>'
        )
        labels.append(
            f'<text x="{x + bar_width / 2}" y="{chart_bottom + 22}" font-size="11" text-anchor="middle" fill="#475569">{row["day"][5:]}</text>'
        )
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#f8fafc" rx="18"/>',
            '<text x="36" y="42" font-size="24" font-family="ui-sans-serif, system-ui" fill="#0f172a">Tracked Activity By Day</text>',
            '<text x="36" y="66" font-size="13" font-family="ui-sans-serif, system-ui" fill="#475569">Observed elapsed minutes from tracked sessions</text>',
            f'<line x1="{chart_left}" y1="{chart_bottom}" x2="{chart_left + chart_width}" y2="{chart_bottom}" stroke="#cbd5e1" stroke-width="2"/>',
            f'<line x1="{chart_left}" y1="{chart_bottom - chart_height}" x2="{chart_left}" y2="{chart_bottom}" stroke="#cbd5e1" stroke-width="2"/>',
            *bars,
            *labels,
            "</svg>",
        ]
    )


def render_evidence_svg(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    metrics = [
        ("Sessions", summary["session_count"]),
        ("Commits", summary["commit_count"]),
        ("Notes", summary["note_count"]),
        ("Files", summary["file_count"]),
        ("Prompts", summary["prompt_count"]),
        ("Tools", summary["tool_event_count"]),
    ]
    max_value = max(max(value, 1) for _, value in metrics)
    width = 760
    height = 320
    bar_left = 170
    bar_width = 500
    start_y = 72
    row_gap = 34
    rows = []
    for index, (label, value) in enumerate(metrics):
        y = start_y + index * row_gap
        current_width = int((value / max_value) * bar_width) if max_value else 0
        rows.append(
            f'<text x="36" y="{y + 15}" font-size="14" font-family="ui-sans-serif, system-ui" fill="#0f172a">{label}</text>'
            f'<rect x="{bar_left}" y="{y}" width="{bar_width}" height="20" rx="10" fill="#e2e8f0" />'
            f'<rect x="{bar_left}" y="{y}" width="{current_width}" height="20" rx="10" fill="#0f766e" />'
            f'<text x="{bar_left + bar_width + 12}" y="{y + 15}" font-size="13" font-family="ui-sans-serif, system-ui" fill="#334155">{value}</text>'
        )
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#f8fafc" rx="18"/>',
            '<text x="36" y="42" font-size="24" font-family="ui-sans-serif, system-ui" fill="#0f172a">Work Evidence Overview</text>',
            '<text x="36" y="66" font-size="13" font-family="ui-sans-serif, system-ui" fill="#475569">Counts of concrete tracked artifacts in this reporting window</text>',
            *rows,
            "</svg>",
        ]
    )


def persist_report(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    payload: dict[str, Any],
    report_markdown: str,
) -> None:
    session_ids = [session["id"] for session in payload["sessions"]]
    commit_ids = [commit["id"] for commit in payload["commits"]]
    conn.execute(
        """
        INSERT INTO reports (
            project_id, range_start, range_end, report_type, generated_at, input_session_ids_json,
            input_commit_ids_json, report_markdown, report_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            payload["window"]["start"],
            payload["window"]["end"],
            f"{payload.get('scope', 'project')}_summary",
            utc_now(),
            json.dumps(session_ids),
            json.dumps(commit_ids),
            report_markdown,
            json.dumps(payload, sort_keys=True),
        ),
    )
