from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from claude_code_thy import APP_DISPLAY_NAME, APP_VERSION

from .types import PromptContextData

if TYPE_CHECKING:
    from claude_code_thy.models import SessionTranscript
    from claude_code_thy.services import ToolServices


class PromptContextBuilder:
    """负责收集渲染 prompt 所需的动态上下文。"""

    def build(
        self,
        session: "SessionTranscript",
        services: "ToolServices",
        *,
        provider_name: str,
        model: str,
    ) -> PromptContextData:
        """为当前会话收集环境、MCP、用户和项目上下文。"""
        workspace_root = services.workspace_root.resolve()
        session_cwd = Path(session.cwd).resolve()

        user_context, user_context_files = self._collect_user_context(workspace_root, session_cwd)
        project_context, project_context_files = self._collect_project_context(workspace_root)
        mcp_instructions, connected_servers = self._collect_mcp_instructions(services)
        skill_names = [
            command.name
            for command in services.command_registry.list_model_commands(session, services)
        ]

        variables = {
            "app_name": APP_DISPLAY_NAME,
            "app_version": APP_VERSION,
            "workspace_root": str(workspace_root),
            "session_cwd": str(session_cwd),
            "provider_name": provider_name,
            "model": model,
            "current_date": datetime.now().astimezone().date().isoformat(),
            "shell": os.environ.get("SHELL", "unknown"),
            "os_name": platform.platform(),
            "user_context": user_context,
            "project_context": project_context,
            "mcp_instructions": mcp_instructions,
            "connected_mcp_servers": ", ".join(connected_servers),
        }

        debug_meta = {
            "user_context_files": user_context_files,
            "project_context_files": project_context_files,
            "connected_mcp_servers": connected_servers,
            "available_skill_names": skill_names,
            "skill_count": len(skill_names),
        }
        return PromptContextData(variables=variables, debug_meta=debug_meta)

    def _collect_user_context(self, workspace_root: Path, session_cwd: Path) -> tuple[str, list[str]]:
        """读取工作区内相关的 `CLAUDE.md` 文件并拼成用户上下文。"""
        files: list[Path] = []
        current = session_cwd
        while True:
            candidate = current / "CLAUDE.md"
            if candidate.exists() and candidate.is_file():
                files.append(candidate.resolve())
            if current == workspace_root or current.parent == current:
                break
            current = current.parent

        deduped: list[Path] = []
        seen: set[str] = set()
        for path in reversed(files):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)

        blocks: list[str] = []
        for path in deduped:
            text = self._safe_read_text(path)
            if not text:
                continue
            relative = self._display_relative(path, workspace_root)
            blocks.append(f"## {relative}\n\n{text}")

        return "\n\n".join(blocks).strip(), [str(path) for path in deduped]

    def _collect_project_context(self, workspace_root: Path) -> tuple[str, list[str]]:
        """读取项目补充上下文文件，并附带只读 git 快照。"""
        candidates = [
            workspace_root / ".claude-code-thy" / "PROJECT_CONTEXT.md",
            workspace_root / "PROJECT_CONTEXT.md",
        ]
        files: list[str] = []
        blocks: list[str] = []
        for path in candidates:
            if not path.exists() or not path.is_file():
                continue
            text = self._safe_read_text(path)
            if not text:
                continue
            files.append(str(path.resolve()))
            relative = self._display_relative(path.resolve(), workspace_root)
            blocks.append(f"## {relative}\n\n{text}")

        git_snapshot = self._git_snapshot(workspace_root)
        if git_snapshot:
            blocks.append(f"## git snapshot\n\n{git_snapshot}")
        return "\n\n".join(blocks).strip(), files

    def _collect_mcp_instructions(self, services: "ToolServices") -> tuple[str, list[str]]:
        """收集当前已连接 MCP server 的 instructions 文本。"""
        blocks: list[str] = []
        connected_servers: list[str] = []
        snapshot = getattr(services.mcp_manager, "snapshot", None)
        if not callable(snapshot):
            return "", connected_servers
        for connection in snapshot():
            if str(connection.status) != "connected":
                continue
            connected_servers.append(str(connection.name))
            instructions = str(connection.instructions or "").strip()
            if not instructions:
                continue
            blocks.append(f"## {connection.name}\n\n{instructions}")
        return "\n\n".join(blocks).strip(), connected_servers

    def _git_snapshot(self, workspace_root: Path) -> str:
        """读取一份降噪后的只读 git 状态快照。"""
        command = [
            "git",
            "-c",
            "core.quotepath=false",
            "status",
            "--short",
            "--branch",
            "--untracked-files=no",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        output = (result.stdout or "").strip()
        if not output:
            return ""
        lines = output.splitlines()
        branch_line = lines[0].strip() if lines and lines[0].startswith("## ") else ""
        entries = [line.rstrip() for line in lines[1:] if line.strip()]
        if not entries:
            return ""

        summary_lines: list[str] = []
        if branch_line:
            summary_lines.append(branch_line)
        summary_lines.append(f"Tracked changes: {len(entries)}")

        counts = self._summarize_git_status(entries)
        if counts:
            summary_lines.append(
                "Counts: " + ", ".join(f"{name}={value}" for name, value in counts.items())
            )

        preview_limit = 8
        summary_lines.append("Changed files:")
        summary_lines.extend(entries[:preview_limit])
        if len(entries) > preview_limit:
            summary_lines.append(f"... and {len(entries) - preview_limit} more")
        return self._truncate("\n".join(summary_lines), 2000)

    def _summarize_git_status(self, entries: list[str]) -> dict[str, int]:
        """把 git status 条目归并成更紧凑的统计信息。"""
        counters = {
            "modified": 0,
            "added": 0,
            "deleted": 0,
            "renamed": 0,
            "conflicts": 0,
            "other": 0,
        }
        for entry in entries:
            status = entry[:2]
            flags = {char for char in status if char.strip()}
            if "U" in flags:
                counters["conflicts"] += 1
                continue
            if "R" in flags:
                counters["renamed"] += 1
                continue
            if "A" in flags:
                counters["added"] += 1
            if "D" in flags:
                counters["deleted"] += 1
            if "M" in flags:
                counters["modified"] += 1
            if not flags or flags.isdisjoint({"A", "D", "M", "R", "U"}):
                counters["other"] += 1
        return {key: value for key, value in counters.items() if value > 0}

    def _safe_read_text(self, path: Path) -> str:
        """安全读取文本文件，并裁剪极长内容。"""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        return self._truncate(text.strip(), 12_000)

    def _display_relative(self, path: Path, workspace_root: Path) -> str:
        """把绝对路径尽量转成工作区相对路径，便于调试输出。"""
        try:
            return str(path.relative_to(workspace_root))
        except ValueError:
            return str(path)

    def _truncate(self, text: str, limit: int) -> str:
        """把超长上下文裁剪到固定长度，避免 prompt 失控膨胀。"""
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."
