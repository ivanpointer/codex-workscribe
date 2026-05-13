---
name: workscribe-session-tools
description: Use when the user wants to record a notable work note, summarize the current Codex session, or explicitly end a session in the codex-workscribe ledger.
---

# Workscribe Session Tools

Use this skill when the user wants to add a manual billing or work-summary note to the telemetry ledger.

## Commands

### Add a note

Use this when the user wants to record something notable mid-session without ending the session.

```bash
workscribe note --path "$PWD" --type note "Short summary of the notable work or context."
```

If the note is specifically a risk, blocker, or decision, set a more specific type:

```bash
workscribe note --path "$PWD" --type blocker "Blocked on Azure DevOps permissions."
workscribe note --path "$PWD" --type decision "Chose SQLite as the telemetry source of truth."
```

### End a session

Use this when the user wants to explicitly summarize and close the current active session.

```bash
workscribe end-session --path "$PWD" "Summarize the work completed in this session."
```

If the user wants a summary note without closing the session, use:

```bash
workscribe end-session --keep-open --path "$PWD" "Session summary so far."
```

## Guidance

- Prefer concise, concrete summaries tied to deliverables, decisions, blockers, or verification.
- If the user asks to record a note for a specific session, pass `--session-key`.
- If the user asks to close a session, use `workscribe end-session` instead of `workscribe note`.
- Do not invent work that did not happen; summarize only what is visible from the current session context.
