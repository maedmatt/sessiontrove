"""Archive local coding-agent sessions."""

import fnmatch
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True, slots=True)
class Source:
    agent: str
    path: Path
    target: Path
    patterns: tuple[str, ...]
    exclude_patterns: tuple[str, ...] = ()


_SAFE_MACHINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def default_sources(
    home: Path | None = None, environ: Mapping[str, str] | None = None
) -> tuple[Source, ...]:
    """Return the known session locations for the current user."""

    home = (home or Path.home()).expanduser()
    environ = os.environ if environ is None else environ
    claude_home = Path(environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
    omp_override = environ.get("PI_CODING_AGENT_DIR", "").strip()
    omp_home = Path(omp_override or home / ".omp/agent").expanduser()
    openclaw_override = environ.get("OPENCLAW_STATE_DIR", "").strip()
    openclaw_home = Path(openclaw_override or home / ".openclaw").expanduser()
    openclaw_agents = openclaw_home / "agents"
    openclaw_sources = []
    if openclaw_agents.is_dir() and not openclaw_agents.is_symlink():
        for agent_path in sorted(openclaw_agents.iterdir(), key=lambda path: path.name):
            sessions = agent_path / "sessions"
            if (
                agent_path.is_dir()
                and not agent_path.is_symlink()
                and sessions.is_dir()
                and not sessions.is_symlink()
            ):
                openclaw_sources.append(
                    Source(
                        "openclaw",
                        sessions,
                        Path("agents") / agent_path.name / "sessions",
                        ("*",),
                        ("*.lock", "*.tmp"),
                    )
                )

    return (
        Source(
            "claude-code",
            claude_home / "projects",
            Path("projects"),
            ("*.jsonl", "agent-*.meta.json"),
        ),
        Source(
            "claude-code",
            claude_home / "history.jsonl",
            Path("history.jsonl"),
            ("*.jsonl",),
        ),
        Source("codex", home / ".codex/sessions", Path("sessions"), ("*.jsonl",)),
        Source(
            "codex",
            home / ".codex/archived_sessions",
            Path("archived_sessions"),
            ("*.jsonl",),
        ),
        Source(
            "codex",
            home / ".codex/history.jsonl",
            Path("history.jsonl"),
            ("*.jsonl",),
        ),
        Source(
            "pi",
            home / ".pi/agent/sessions",
            Path("sessions"),
            ("*.jsonl",),
        ),
        Source(
            "omp",
            omp_home / "sessions",
            Path("sessions"),
            ("*",),
            ("*.lock", "*.tmp"),
        ),
        *openclaw_sources,
    )


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _matches(relative: Path, source: Source) -> bool:
    return any(
        fnmatch.fnmatch(relative.name, pattern) for pattern in source.patterns
    ) and not any(
        fnmatch.fnmatch(relative.name, pattern) for pattern in source.exclude_patterns
    )


def _files(source: Source) -> list[tuple[Path, Path]]:
    root = _absolute(source.path)
    if root.is_symlink():
        return []
    if root.is_file():
        relative = Path(root.name)
        return [(root, source.target)] if _matches(relative, source) else []
    if not root.is_dir():
        return []

    selected = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        names[:] = sorted(name for name in names if not (current / name).is_symlink())
        for filename in sorted(filenames):
            path = current / filename
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root)
            if _matches(relative, source):
                selected.append((path, source.target / relative))
    return selected


def _prepare(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)


def _unchanged(source: Path, destination: Path) -> bool:
    if destination.is_symlink() or not destination.is_file():
        return False
    left = source.stat(follow_symlinks=False)
    right = destination.stat(follow_symlinks=False)
    return left.st_size == right.st_size and left.st_mtime_ns == right.st_mtime_ns


def _copy(source: Path, destination: Path) -> bool:
    if _unchanged(source, destination):
        return False
    _prepare(destination)
    temporary: str | None = None
    try:
        with NamedTemporaryFile(
            dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as handle:
            temporary = handle.name
        shutil.copy2(source, temporary, follow_symlinks=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        temporary = None
        return True
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def archive(
    destination: Path,
    machine: str,
    sources: Sequence[Source] | None = None,
) -> dict[str, int]:
    """Archive changed session files under one machine directory."""

    if not _SAFE_MACHINE.fullmatch(machine):
        raise ValueError(
            "machine must contain only letters, numbers, dots, dashes, and underscores"
        )
    destination = _absolute(destination)
    sources = default_sources() if sources is None else sources
    for source in sources:
        root = _absolute(source.path)
        if root.is_dir() and (destination == root or destination.is_relative_to(root)):
            raise ValueError(f"destination cannot be inside {root}")

    destination.mkdir(parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    machine_destination = destination / machine
    machine_destination.mkdir(exist_ok=True)
    os.chmod(machine_destination, 0o700)

    results: dict[str, int] = {}
    for source in sources:
        if not _absolute(source.path).exists():
            continue
        results.setdefault(source.agent, 0)
        for path, relative in _files(source):
            target = machine_destination / source.agent / relative
            results[source.agent] += _copy(path, target)
    return results
