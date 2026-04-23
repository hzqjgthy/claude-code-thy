from __future__ import annotations

from claude_code_thy.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

from .prompt import DESCRIPTION


class SkillTool(Tool):
    """实现 `Skill` 工具。"""
    name = "skill"
    description = DESCRIPTION
    input_schema = {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "Skill command name."},
            "args": {"type": "string", "description": "Optional skill arguments."},
        },
        "required": ["skill"],
    }

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        """阻止用户以原始字符串参数直接调用 `skill` 工具。"""
        _ = (raw_args, context)
        raise ToolError("工具 `skill` 不支持字符串参数执行")

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        """处理模型侧结构化 `skill` 工具调用。"""
        if context.services is None:
            raise ToolError("Skill registry is unavailable")

        skill_name = str(input_data.get("skill", "")).strip()
        raw_args = str(input_data.get("args", "")).strip()
        if not skill_name:
            raise ToolError("tool input 缺少 skill")

        session = context.services.command_session_for(context.session_id)
        command, prompt = resolve_skill_prompt(
            session,
            context.services,
            skill_name,
            raw_args,
            user_invoked=False,
        )

        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"Skill: {command.name}",
            display_name="Skill",
            ui_kind="skill",
            output=prompt,
            metadata={
                "command_name": command.name,
                "loaded_from": command.loaded_from,
            },
            structured_data={
                "command_name": command.name,
                "loaded_from": command.loaded_from,
                "prompt": prompt,
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


def describe_user_skills(session, services) -> str:
    """返回用户当前可显式执行的 skill 列表，不包含 MCP prompt。"""
    lines = [
        f"- {spec.name}: {spec.description}"
        for spec in services.command_registry.list_user_commands(session, services)
        if spec.kind != "mcp_prompt"
    ]
    return "\n".join(lines) or "当前没有可用 skills。"


def resolve_skill_prompt(
    session,
    services,
    skill_name: str,
    raw_args: str,
    *,
    user_invoked: bool,
):
    """按调用来源解析目标 skill，并渲染出最终 prompt 文本。"""
    if user_invoked:
        command = next(
            (
                spec
                for spec in services.command_registry.list_user_commands(session, services)
                if spec.kind != "mcp_prompt" and spec.name == skill_name
            ),
            None,
        )
        available = describe_user_skills(session, services)
    else:
        command = services.command_registry.find_model_command(
            session,
            services,
            skill_name,
        )
        available = services.command_registry.describe_model_commands(session, services)

    if command is None:
        raise ToolError(f"未找到 skill：{skill_name}\n\n可用 skills:\n{available}")

    prompt = services.command_registry.render_prompt(
        command,
        raw_args,
        session,
        services,
    )
    if not prompt.strip():
        raise ToolError(f"skill `{skill_name}` 没有生成可执行内容")
    return command, prompt
