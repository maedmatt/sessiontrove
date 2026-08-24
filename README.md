# Sessiontrove

Sessiontrove copies local coding-agent conversations into one private archive. It keeps each agent's raw format, updates changed files, and never deletes an archived file when the original disappears.

It does not upload or normalize conversations. A built-in viewer lets you read the archive in the browser.

>[!IMPORTANT] 
>**For now, its purpose is simple**: preserve your own conversations as source data you could later use to fine-tune future agents on how you work.

## Archive

Sessiontrove requires Python 3.11 or newer. From this repository, run:

```bash
uv run sessiontrove archive ~/Backups/agent-sessions --machine macbookpro-m4
```

The machine name creates a stable top-level directory, such as `agent-sessions/macbookpro-m4`, so several computers can share one archive. Use the same name on every run. Missing agents are skipped automatically. Archive directories use mode `0700`, and copied files use `0600`.

To install the command:

```bash
uv tool install .
sessiontrove archive ~/Backups/agent-sessions --machine macbookpro-m4
```

## View

```bash
sessiontrove view ~/Backups/agent-sessions
```

This starts a read-only server on `127.0.0.1` with an automatic port and opens
the browser. Use `--port` to pick a port and `--no-browser` to only print the
URL. The viewer shows a searchable session list and, per session, the
conversation, reasoning, tool calls and results, the branch tree, and basic
metadata such as model and cost. Reasoning and tool output are collapsible,
one block at a time or all at once with the `t` and `o` keys, and records the
viewer does not recognize fall back to their raw JSON. It follows the system
light or dark preference and ships the [Fira Code](https://github.com/tonsky/FiraCode)
font, which is redistributed under the SIL Open Font License.

The viewer never modifies the archive: sessions are parsed in memory only when
opened, symlinks are ignored, and files outside the archive are never served.
It currently reads Pi sessions; readers for the other agents can be added
later. It serves no external resources and makes no network requests beyond
your own localhost.

## Supported agents

| Agent | Session data |
| --- | --- |
| Claude Code | Project transcripts and `history.jsonl` under `$CLAUDE_CONFIG_DIR` or `~/.claude` |
| Codex | `~/.codex/sessions`, `~/.codex/archived_sessions`, and `~/.codex/history.jsonl` |
| Oh My Pi (OMP) | `sessions` under `$PI_CODING_AGENT_DIR` or `~/.omp/agent` |
| OpenClaw | Every agent's `sessions` directory under `$OPENCLAW_STATE_DIR/agents` or `~/.openclaw/agents` |
| Pi | `~/.pi/agent/sessions` |

Claude and Codex history files hold long-lived user prompts; project and rollout files hold the full transcripts. OpenClaw archives include its session index, transcripts, reset and deleted sessions, trajectories, caches, and migration or repair artifacts. Temporary and lock files are skipped.

### Keep Claude Code transcripts

Claude Code deletes local transcripts after 30 days by default. Sessiontrove cannot archive a transcript that Claude Code has already deleted. 
> [!WARNING]
> Set a long retention period in `~/.claude/settings.json` before relying on the archive:
```json
{
  "cleanupPeriodDays": 36500
}
```
`36500` keeps transcripts for roughly 100 years. Claude Code has no "forever" value: the minimum is `1`, and `0` is invalid. See the official [`cleanupPeriodDays`](https://code.claude.com/docs/en/settings-reference#cleanupperioddays) reference.

### Keep Codex history

Codex has no documented retention setting for full rollout files. Its separate prompt history is saved without a size limit by default. To make that behavior explicit, use this in `~/.codex/config.toml`:

```toml
[history]
persistence = "save-all"
```

Do not set `history.max_bytes` if you want to retain every prompt: Codex drops the oldest entries when that limit is reached. This setting controls `history.jsonl`, not the full rollouts under `sessions` and `archived_sessions`. See the official [Codex configuration reference](https://developers.openai.com/codex/config-reference).

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Conversation archives can contain prompts, code, tool output, local paths, and secrets. Keep them outside this repository and do not make them public.

Sessiontrove is available under the [MIT License](LICENSE).
