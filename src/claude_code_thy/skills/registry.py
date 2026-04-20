from __future__ import annotations

import fnmatch
import shlex
from pathlib import Path

from claude_code_thy.mcp.utils import run_async_sync
from claude_code_thy.models import SessionTranscript

from .loader import SkillLoader
from .mcp_bridge import build_mcp_prompt_specs
from .types import PromptCommandSpec


class PromptCommandRegistry:
    def __init__(self, workspace_root: Path, settings) -> None:
        self.workspace_root = workspace_root.resolve()
        self.settings = settings
        self.loader = SkillLoader(self.workspace_root)

    def list_user_commands(
        self,
        session: SessionTranscript,
        services,
        *,
        include_mcp_prompts: bool = True,
    ) -> list[PromptCommandSpec]:
        commands = self._list_commands(session, services, include_mcp_prompts=include_mcp_prompts)
        return [command for command in commands if command.user_invocable]

    def list_model_commands(
        self,
        session: SessionTranscript,
        services,
    ) -> list[PromptCommandSpec]:
        commands = self._list_commands(session, services, include_mcp_prompts=False)
        return [command for command in commands if command.model_invocable]

    def find_user_command(
        self,
        session: SessionTranscript,
        services,
        command_name: str,
    ) -> PromptCommandSpec | None:
        normalized = command_name[1:] if command_name.startswith("/") else command_name
        for command in self.list_user_commands(session, services):
            if command.name == normalized:
                return command
        return None

    def find_model_command(
        self,
        session: SessionTranscript,
        services,
        command_name: str,
    ) -> PromptCommandSpec | None:
        for command in self.list_model_commands(session, services):
            if command.name == command_name:
                return command
        return None

    def render_prompt(
        self,
        command: PromptCommandSpec,
        raw_args: str,
        session: SessionTranscript,
        services,
    ) -> str:
        if command.kind == "mcp_prompt":
            if not command.server_name or not command.original_name:
                return ""
            arguments = self._build_prompt_arguments(command.arg_names, raw_args)
            get_prompt_sync = getattr(services.mcp_manager, "get_prompt_sync", None)
            if callable(get_prompt_sync):
                result = get_prompt_sync(command.server_name, command.original_name, arguments)
            else:
                result = run_async_sync(
                    services.mcp_manager.get_prompt(
                        command.server_name,
                        command.original_name,
                        arguments,
                    )
                )
            from claude_code_thy.mcp.serializers import render_prompt_result

            return render_prompt_result(result).strip()

        content = command.content or ""
        if command.skill_root:
            content = f"Base directory for this skill: {command.skill_root}\n\n{content}"
        content = content.replace("${CLAUDE_SESSION_ID}", session.session_id)
        if command.skill_root:
            content = content.replace("${CLAUDE_SKILL_DIR}", command.skill_root)
        return self._substitute_arguments(content, raw_args, command.arg_names).strip()

    def describe_model_commands(
        self,
        session: SessionTranscript,
        services,
        *,
        limit: int = 24,
    ) -> str:
        commands = self.list_model_commands(session, services)
        if not commands:
            return "No skills available."
        lines: list[str] = []
        for command in commands[:limit]:
            suffix = f" ({command.execution_context})" if command.execution_context != "inline" else ""
            lines.append(f"- {command.name}{suffix}: {command.description}")
        if len(commands) > limit:
            lines.append(f"- ... and {len(commands) - limit} more")
        return "\n".join(lines)

    def _list_commands(
        self,
        session: SessionTranscript,
        services,
        *,
        include_mcp_prompts: bool,
    ) -> list[PromptCommandSpec]:
        state = services.command_state_for_session(session.session_id)
        local_commands = self._list_local_commands(state.skill_dirs, state.touched_paths)
        deduped: dict[str, PromptCommandSpec] = {command.name: command for command in local_commands}

        if include_mcp_prompts:
            for command in self._cached_mcp_prompt_commands(services):
                deduped.setdefault(command.name, command)
        for command in self._cached_mcp_skill_commands(services):
            deduped.setdefault(command.name, command)
        return [deduped[name] for name in sorted(deduped)]

    def _cached_mcp_prompt_commands(self, services) -> list[PromptCommandSpec]:
        cached = getattr(services.mcp_manager, "cached_prompt_commands", None)
        if callable(cached):
            return list(cached())
        prompt_defs_fn = getattr(services.mcp_manager, "cached_prompts", None)
        if not callable(prompt_defs_fn):
            return []
        prompt_specs: list[PromptCommandSpec] = []
        for server_name, definitions in prompt_defs_fn().items():
            prompt_specs.extend(build_mcp_prompt_specs(server_name, list(definitions)))
        return prompt_specs

    def _cached_mcp_skill_commands(self, services) -> list[PromptCommandSpec]:
        cached = getattr(services.mcp_manager, "cached_skill_commands", None)
        if callable(cached):
            return list(cached())
        return []

    def _list_local_commands(
        self,
        skill_dirs: set[str],
        touched_paths: set[str],
    ) -> list[PromptCommandSpec]:
        command_map: dict[str, PromptCommandSpec] = {}

        for root_dir in self._local_root_dirs():
            for loaded in self.loader.load_from_skill_root(root_dir):
                if self._include_command(loaded.command, touched_paths):
                    command_map.setdefault(loaded.command.name, loaded.command)

        discovered_dirs = sorted(
            {Path(path).resolve() for path in skill_dirs},
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for skill_dir in discovered_dirs:
            loaded = self.loader.load_from_skill_dir(skill_dir)
            if loaded is None:
                continue
            if not self._include_command(loaded.command, touched_paths):
                continue
            command_map[loaded.command.name] = loaded.command

        return [command_map[name] for name in sorted(command_map)]

    def _local_root_dirs(self) -> list[Path]:
        roots: list[Path] = []
        default_root = self.workspace_root / ".claude-code-thy" / "skills"
        if default_root.exists():
            roots.append(default_root.resolve())
        for configured in self.settings.search_roots:
            root = (self.workspace_root / configured).resolve()
            if root.exists():
                roots.append(root)
        deduped: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(root)
        return deduped

    def _include_command(
        self,
        command: PromptCommandSpec,
        touched_paths: set[str],
    ) -> bool:
        if not command.paths:
            return True
        for touched in touched_paths:
            relative = self._relative_path(Path(touched))
            if any(fnmatch.fnmatch(relative, pattern) for pattern in command.paths):
                return True
        return False

    def _relative_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workspace_root))
        except ValueError:
            return str(path.resolve())

    def _substitute_arguments(
        self,
        content: str,
        raw_args: str,
        arg_names: tuple[str, ...],
    ) -> str:
        values = self._build_prompt_arguments(arg_names, raw_args)
        if not values and raw_args.strip():
            values = {"args": raw_args.strip()}
        result = content
        for name, value in values.items():
            result = result.replace(f"${{{name}}}", value)
            result = result.replace(f"{{{{{name}}}}}", value)
        if "args" not in values:
            result = result.replace("${args}", raw_args.strip())
            result = result.replace("{{args}}", raw_args.strip())
        return result

    def _build_prompt_arguments(
        self,
        arg_names: tuple[str, ...],
        raw_args: str,
    ) -> dict[str, str]:
        text = raw_args.strip()
        if not arg_names:
            return {}
        if len(arg_names) == 1:
            return {arg_names[0]: text}

        tokens = shlex.split(text) if text else []
        result: dict[str, str] = {}
        indexed = [token for token in tokens if "=" not in token]
        for token in tokens:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            key = key.strip()
            if key in arg_names:
                result[key] = value.strip()
        for name, value in zip(arg_names, indexed, strict=False):
            result.setdefault(name, value)
        return result
