# Sessiontrove

Sessiontrove copies local coding-agent conversations into one private archive. It
keeps each tool's raw format, updates changed files, and never deletes an archived
file when the original disappears.

It does not upload, parse, or normalize conversations. That makes the archive a
small, lossless source for later processing or fine-tuning work.

## Use

Sessiontrove requires Python 3.11 or newer. From this repository, run:

```bash
uv run sessiontrove ~/Backups/agent-sessions
```

Run the same command whenever you want to update the archive. Missing tools are
skipped automatically. The destination is created with mode `0700`, and copied
files use `0600`.

To install the command:

```bash
uv tool install .
sessiontrove ~/Backups/agent-sessions
```

## Supported tools

| Tool | Session data |
| --- | --- |
| Claude Code | `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects` |
| Codex | `~/.codex/sessions` and `~/.codex/archived_sessions` |
| OpenCode | `$XDG_DATA_HOME/opencode/opencode.db` and legacy `storage` JSON |
| Pi | `~/.pi/agent/sessions` |

`XDG_DATA_HOME` defaults to `~/.local/share`.

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
