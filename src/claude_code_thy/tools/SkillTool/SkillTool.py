from __future__ import annotations

from claude_code_thy.tools.AgentTool import AgentTool
from claude_code_thy.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

from .prompt import DESCRIPTION, USAGE


class SkillTool(Tool):
    """实现 `Skill` 工具。"""
    name = "skill"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "Skill command name."},
            "args": {"type": "string", "description": "Optional skill arguments."},
        },
        "required": ["skill"],
    }

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        """解析 `raw_input`。"""
        _ = context
        text = raw_args.strip()
        if not text:
            raise ToolError("用法：/skill <skill_name> [args]")
        skill_name, _, args = text.partition(" ")
        return {"skill": skill_name.strip(), "args": args.strip()}

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        """执行当前流程。"""
        return self.execute_input(self.parse_raw_input(raw_args, context), context)

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        """执行 `input`。"""
        if context.services is None:
            raise ToolError("Skill registry is unavailable")

        skill_name = str(input_data.get("skill", "")).strip()
        raw_args = str(input_data.get("args", "")).strip()
        if not skill_name:
            raise ToolError("tool input 缺少 skill")

        session = context.services.command_session_for(context.session_id)
        command = context.services.command_registry.find_model_command(
            session,
            context.services,
            skill_name,
        )
        if command is None:
            available = context.services.command_registry.describe_model_commands(session, context.services)
            raise ToolError(f"未找到 skill：{skill_name}\n\n可用 skills:\n{available}")

        prompt = context.services.command_registry.render_prompt(
            command,
            raw_args,
            session,
            context.services,
        )
        if not prompt.strip():
            raise ToolError(f"skill `{skill_name}` 没有生成可执行内容")

        if command.execution_context == "fork":
            return self._execute_forked(command, prompt, context)

        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"Skill inline: {command.name}",
            display_name="Skill",
            ui_kind="skill",
            output=prompt,
            metadata={
                "command_name": command.name,
                "loaded_from": command.loaded_from,
                "execution_context": command.execution_context,
            },
            structured_data={
                "command_name": command.name,
                "loaded_from": command.loaded_from,
                "execution_context": command.execution_context,
                "prompt": prompt,
                "allowed_tools": list(command.allowed_tools),
            },
            tool_result_content=prompt,
        )

    def to_spec_for_context(self, context: ToolContext | None = None) -> ToolSpec:
        """转换为 `spec_for_context`。"""
        if context is None or context.services is None:
            return super().to_spec()
        session = context.services.command_session_for(context.session_id)
        description = (
            f"{DESCRIPTION}\n\n可用 skills:\n"
            f"{context.services.command_registry.describe_model_commands(session, context.services)}"
        )
        return ToolSpec(
            name=self.name,
            description=description,
            input_schema=self.input_schema,
            read_only=self.is_read_only(),
            concurrency_safe=self.is_concurrency_safe(),
            search_behavior=self.search_behavior(),
        )

    def _execute_forked(self, command, prompt: str, context: ToolContext) -> ToolResult:
        """执行 `forked`。"""
        agent_prompt = self._decorate_fork_prompt(command, prompt)
        return AgentTool().execute_input(
            {
                "prompt": agent_prompt,
                "description": f"Skill: {command.name}",
                "model": command.model,
                "run_in_background": False,
            },
            context,
        )

    def _decorate_fork_prompt(self, command, prompt: str) -> str:
        """处理 `decorate_fork_prompt`。"""
        lines = [prompt.strip()]
        if command.allowed_tools:
            lines.append("")
            lines.append("Recommended tools for this skill:")
            lines.extend(f"- {name}" for name in command.allowed_tools)
        if command.effort:
            lines.append("")
            lines.append(f"Recommended effort: {command.effort}")
        return "\n".join(line for line in lines if line is not None)
