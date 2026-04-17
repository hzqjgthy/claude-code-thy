from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ToolPermissionRule:
    effect: str
    tool: str
    pattern: str
    target: str = "path"
    description: str = ""


@dataclass(slots=True)
class SandboxSettings:
    mode: str = "workspace-write"
    excluded_commands: tuple[str, ...] = ()
    dangerous_commands: tuple[str, ...] = ()
    allow_disable: bool = True
    writable_roots: tuple[str, ...] = ()
    allow_network: bool = True


@dataclass(slots=True)
class TaskSettings:
    max_background_tasks: int = 20
    tasks_dir: str = ".claude-code-thy/tasks"
    tool_results_dir: str = ".claude-code-thy/tool-results"


@dataclass(slots=True)
class FileHistorySettings:
    enabled: bool = True
    history_dir: str = ".claude-code-thy/file-history"
    max_snapshots_per_file: int = 20


@dataclass(slots=True)
class SkillTrigger:
    pattern: str
    skill_dir: str


@dataclass(slots=True)
class SkillsSettings:
    enabled: bool = True
    search_roots: tuple[str, ...] = ()
    triggers: tuple[SkillTrigger, ...] = ()


@dataclass(slots=True)
class LspServerSettings:
    name: str
    command: tuple[str, ...]
    file_globs: tuple[str, ...]
    root_markers: tuple[str, ...] = ()
    language_id: str | None = None


@dataclass(slots=True)
class LspSettings:
    enabled: bool = False
    servers: tuple[LspServerSettings, ...] = ()


@dataclass(slots=True)
class McpSettings:
    enabled: bool = True
    servers: dict[str, dict[str, object]] = field(default_factory=dict)
    connect_timeout_ms: int = 15_000
    tool_call_timeout_ms: int = 600_000


@dataclass(slots=True)
class AppSettings:
    permission_rules: tuple[ToolPermissionRule, ...] = ()
    read_ignore_patterns: tuple[str, ...] = (
        ".git",
        ".svn",
        ".hg",
        ".bzr",
        ".jj",
        ".sl",
        "__pycache__",
        ".pytest_cache",
    )
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)
    tasks: TaskSettings = field(default_factory=TaskSettings)
    file_history: FileHistorySettings = field(default_factory=FileHistorySettings)
    skills: SkillsSettings = field(default_factory=SkillsSettings)
    lsp: LspSettings = field(default_factory=LspSettings)
    mcp: McpSettings = field(default_factory=McpSettings)

    @classmethod
    def load_for_workspace(cls, cwd: Path) -> "AppSettings":
        settings_path = _resolve_settings_path(cwd)
        if settings_path is None or not settings_path.exists():
            return cls()

        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        return cls(
            permission_rules=_load_permission_rules(raw.get("permissions")),
            read_ignore_patterns=_load_tuple(
                raw.get("read_ignore_patterns"),
                default=cls().read_ignore_patterns,
            ),
            sandbox=_load_sandbox_settings(raw.get("sandbox")),
            tasks=_load_task_settings(raw.get("tasks")),
            file_history=_load_file_history_settings(raw.get("file_history")),
            skills=_load_skills_settings(raw.get("skills")),
            lsp=_load_lsp_settings(raw.get("lsp")),
            mcp=_load_mcp_settings(raw.get("mcp")),
        )


def validate_settings_document(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["settings 文档必须是 JSON object。"]

    permissions = data.get("permissions")
    if permissions is not None and not isinstance(permissions, list):
        errors.append("permissions 必须是数组。")

    read_ignore = data.get("read_ignore_patterns")
    if read_ignore is not None and not isinstance(read_ignore, list):
        errors.append("read_ignore_patterns 必须是字符串数组。")

    sandbox = data.get("sandbox")
    if sandbox is not None:
        if not isinstance(sandbox, dict):
            errors.append("sandbox 必须是 object。")
        else:
            errors.extend(_validate_sandbox_document(sandbox))

    tasks = data.get("tasks")
    if tasks is not None:
        if not isinstance(tasks, dict):
            errors.append("tasks 必须是 object。")
        else:
            if "max_background_tasks" in tasks and not isinstance(tasks["max_background_tasks"], int):
                errors.append("tasks.max_background_tasks 必须是整数。")

    file_history = data.get("file_history")
    if file_history is not None:
        if not isinstance(file_history, dict):
            errors.append("file_history 必须是 object。")
        else:
            if "enabled" in file_history and not isinstance(file_history["enabled"], bool):
                errors.append("file_history.enabled 必须是布尔值。")
            if "max_snapshots_per_file" in file_history and not isinstance(file_history["max_snapshots_per_file"], int):
                errors.append("file_history.max_snapshots_per_file 必须是整数。")

    skills = data.get("skills")
    if skills is not None:
        if not isinstance(skills, dict):
            errors.append("skills 必须是 object。")
        else:
            if "enabled" in skills and not isinstance(skills["enabled"], bool):
                errors.append("skills.enabled 必须是布尔值。")
            if "search_roots" in skills and not isinstance(skills["search_roots"], list):
                errors.append("skills.search_roots 必须是数组。")
            if "triggers" in skills and not isinstance(skills["triggers"], list):
                errors.append("skills.triggers 必须是数组。")

    lsp = data.get("lsp")
    if lsp is not None:
        if not isinstance(lsp, dict):
            errors.append("lsp 必须是 object。")
        else:
            if "enabled" in lsp and not isinstance(lsp["enabled"], bool):
                errors.append("lsp.enabled 必须是布尔值。")
            if "servers" in lsp and not isinstance(lsp["servers"], list):
                errors.append("lsp.servers 必须是数组。")

    mcp = data.get("mcp")
    if mcp is not None:
        if not isinstance(mcp, dict):
            errors.append("mcp 必须是 object。")
        else:
            if "enabled" in mcp and not isinstance(mcp["enabled"], bool):
                errors.append("mcp.enabled 必须是布尔值。")
            if "servers" in mcp and not isinstance(mcp["servers"], dict):
                errors.append("mcp.servers 必须是 object。")
            if "connect_timeout_ms" in mcp and not isinstance(mcp["connect_timeout_ms"], int):
                errors.append("mcp.connect_timeout_ms 必须是整数。")
            if "tool_call_timeout_ms" in mcp and not isinstance(mcp["tool_call_timeout_ms"], int):
                errors.append("mcp.tool_call_timeout_ms 必须是整数。")

    return errors


def _resolve_settings_path(cwd: Path) -> Path | None:
    configured = os.environ.get("CLAUDE_CODE_THY_SETTINGS")
    if configured:
        return Path(configured).expanduser().resolve()

    candidates = [
        cwd / ".claude-code-thy" / "settings.json",
        cwd / ".claude-code-thy" / "settings.local.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _validate_sandbox_document(data: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if "mode" in data and not isinstance(data["mode"], str):
        errors.append("sandbox.mode 必须是字符串。")
    if "excluded_commands" in data and not isinstance(data["excluded_commands"], list):
        errors.append("sandbox.excluded_commands 必须是数组。")
    if "dangerous_commands" in data and not isinstance(data["dangerous_commands"], list):
        errors.append("sandbox.dangerous_commands 必须是数组。")
    if "allow_disable" in data and not isinstance(data["allow_disable"], bool):
        errors.append("sandbox.allow_disable 必须是布尔值。")
    if "writable_roots" in data and not isinstance(data["writable_roots"], list):
        errors.append("sandbox.writable_roots 必须是数组。")
    if "allow_network" in data and not isinstance(data["allow_network"], bool):
        errors.append("sandbox.allow_network 必须是布尔值。")
    return errors


def _load_tuple(value: object, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return default
    return tuple(str(item).strip() for item in value if str(item).strip())


def _load_permission_rules(value: object) -> tuple[ToolPermissionRule, ...]:
    if not isinstance(value, list):
        return ()

    rules: list[ToolPermissionRule] = []
    for item in value:
        if isinstance(item, str):
            parts = [part.strip() for part in item.split(":", 3)]
            if len(parts) == 3:
                effect, tool, pattern = parts
                target = "path"
            elif len(parts) == 4:
                effect, tool, target, pattern = parts
            else:
                continue
            rules.append(
                ToolPermissionRule(
                    effect=effect or "allow",
                    tool=tool or "*",
                    target=target or "path",
                    pattern=pattern or "*",
                )
            )
            continue

        if not isinstance(item, dict):
            continue
        rules.append(
            ToolPermissionRule(
                effect=str(item.get("effect", "allow")),
                tool=str(item.get("tool", "*")),
                pattern=str(item.get("pattern", "*")),
                target=str(item.get("target", "path")),
                description=str(item.get("description", "")),
            )
        )
    return tuple(rules)


def _load_sandbox_settings(value: object) -> SandboxSettings:
    if not isinstance(value, dict):
        return SandboxSettings()
    return SandboxSettings(
        mode=str(value.get("mode", "workspace-write")),
        excluded_commands=_load_tuple(value.get("excluded_commands"), default=()),
        dangerous_commands=_load_tuple(value.get("dangerous_commands"), default=()),
        allow_disable=bool(value.get("allow_disable", True)),
        writable_roots=_load_tuple(value.get("writable_roots"), default=()),
        allow_network=bool(value.get("allow_network", True)),
    )


def _load_task_settings(value: object) -> TaskSettings:
    if not isinstance(value, dict):
        return TaskSettings()
    return TaskSettings(
        max_background_tasks=int(value.get("max_background_tasks", 20) or 20),
        tasks_dir=str(value.get("tasks_dir", ".claude-code-thy/tasks")),
        tool_results_dir=str(value.get("tool_results_dir", ".claude-code-thy/tool-results")),
    )


def _load_file_history_settings(value: object) -> FileHistorySettings:
    if not isinstance(value, dict):
        return FileHistorySettings()
    return FileHistorySettings(
        enabled=bool(value.get("enabled", True)),
        history_dir=str(value.get("history_dir", ".claude-code-thy/file-history")),
        max_snapshots_per_file=int(value.get("max_snapshots_per_file", 20) or 20),
    )


def _load_skills_settings(value: object) -> SkillsSettings:
    if not isinstance(value, dict):
        return SkillsSettings()
    triggers_raw = value.get("triggers", [])
    triggers: list[SkillTrigger] = []
    if isinstance(triggers_raw, list):
        for item in triggers_raw:
            if not isinstance(item, dict):
                continue
            pattern = str(item.get("pattern", "")).strip()
            skill_dir = str(item.get("skill_dir", "")).strip()
            if not pattern or not skill_dir:
                continue
            triggers.append(SkillTrigger(pattern=pattern, skill_dir=skill_dir))
    return SkillsSettings(
        enabled=bool(value.get("enabled", True)),
        search_roots=_load_tuple(value.get("search_roots"), default=()),
        triggers=tuple(triggers),
    )


def _load_lsp_settings(value: object) -> LspSettings:
    if not isinstance(value, dict):
        return LspSettings()

    servers: list[LspServerSettings] = []
    raw_servers = value.get("servers", [])
    if isinstance(raw_servers, list):
        for item in raw_servers:
            if not isinstance(item, dict):
                continue
            command = item.get("command")
            file_globs = item.get("file_globs")
            if not isinstance(command, list) or not isinstance(file_globs, list):
                continue
            server = LspServerSettings(
                name=str(item.get("name", "lsp-server")),
                command=tuple(str(part) for part in command if str(part).strip()),
                file_globs=tuple(str(glob) for glob in file_globs if str(glob).strip()),
                root_markers=_load_tuple(item.get("root_markers"), default=()),
                language_id=(
                    str(item.get("language_id")).strip()
                    if item.get("language_id") is not None
                    else None
                ),
            )
            if server.command and server.file_globs:
                servers.append(server)
    return LspSettings(
        enabled=bool(value.get("enabled", False)),
        servers=tuple(servers),
    )


def _load_mcp_settings(value: object) -> McpSettings:
    if not isinstance(value, dict):
        return McpSettings()
    raw_servers = value.get("servers")
    servers: dict[str, dict[str, object]] = {}
    if isinstance(raw_servers, dict):
        for name, server in raw_servers.items():
            if not isinstance(server, dict):
                continue
            servers[str(name)] = {str(key): val for key, val in server.items()}
    return McpSettings(
        enabled=bool(value.get("enabled", True)),
        servers=servers,
        connect_timeout_ms=int(value.get("connect_timeout_ms", 15_000) or 15_000),
        tool_call_timeout_ms=int(value.get("tool_call_timeout_ms", 600_000) or 600_000),
    )
