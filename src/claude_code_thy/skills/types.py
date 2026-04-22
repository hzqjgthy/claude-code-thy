from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


PromptCommandKind = Literal["local_skill", "mcp_prompt", "mcp_skill"]
PromptCommandLoadedFrom = Literal["skills", "mcp_prompt", "mcp"]
PromptExecutionContext = Literal["inline", "fork"]


@dataclass(slots=True)
class PromptCommandSpec:
    """统一描述本地 skill、MCP skill 和 MCP prompt 的可执行元数据。"""
    name: str
    description: str
    kind: PromptCommandKind
    loaded_from: PromptCommandLoadedFrom
    source: Literal["skills", "mcp"]
    content_length: int = 0
    content: str | None = None
    progress_message: str = "running"
    arg_names: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    when_to_use: str | None = None
    version: str | None = None
    model: str | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    execution_context: PromptExecutionContext = "inline"
    agent: str | None = None
    effort: str | None = None
    paths: tuple[str, ...] = ()
    display_name: str | None = None
    skill_root: str | None = None
    server_name: str | None = None
    original_name: str | None = None
    resource_uri: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def user_facing_name(self) -> str:
        """返回展示给用户的名称，没有别名时退回内部命令名。"""
        return self.display_name or self.name

    @property
    def model_invocable(self) -> bool:
        """判断该命令是否允许由模型在自动流程中主动触发。"""
        return self.kind != "mcp_prompt" and not self.disable_model_invocation
