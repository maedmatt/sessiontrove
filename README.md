# Sessiontrove

Sessiontrove copies local coding-agent conversations into one private archive. It
keeps each tool's raw format, updates changed files, and never deletes an archived
file when the original disappears.

It does not upload, parse, or normalize conversations. That makes the archive a
small, lossless source for later processing or fine-tuning work.

## Use

Sessiontrove requires Python 3.11 or newer. From this repository, run:

```bash
uv run sessiontrove ~/Backups/agent-sessions --machine macbookpro-m4
```

The machine name creates a stable top-level directory, such as
`agent-sessions/macbookpro-m4`, so several computers can share one archive. Use
the same name on every run. Missing tools are skipped automatically. Archive
directories use mode `0700`, and copied files use `0600`.

To install the command:

```bash
uv tool install .
sessiontrove ~/Backups/agent-sessions --machine macbookpro-m4
```

## Supported tools

| Tool | Session data |
| --- | --- |
| Claude Code | Project transcripts and `history.jsonl` under `$CLAUDE_CONFIG_DIR` or `~/.claude` |
| Codex | `~/.codex/sessions`, `~/.codex/archived_sessions`, and `~/.codex/history.jsonl` |
| OpenCode | `$XDG_DATA_HOME/opencode/opencode.db` and legacy `storage` JSON |
| Pi | `~/.pi/agent/sessions` |

`XDG_DATA_HOME` defaults to `~/.local/share`. Claude and Codex history files hold
long-lived user prompts; project and rollout files hold the full transcripts.

Current OpenCode releases store conversations in a SQLite database. Sessiontrove
uses SQLite's online backup API so its snapshot includes committed write-ahead-log
data. The database can contain unrelated application state, so treat the whole
archive as sensitive.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Conversation archives can contain prompts, code, tool output, local paths, and
secrets. Keep them outside this repository and do not make them public.

Sessiontrove is available under the [MIT License](LICENSE).
