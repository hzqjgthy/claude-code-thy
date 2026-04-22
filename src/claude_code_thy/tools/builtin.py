from __future__ import annotations

from claude_code_thy.tools.base import Tool
from claude_code_thy.tools.AgentTool import AgentTool
from claude_code_thy.tools.BashTool import BashTool
from claude_code_thy.tools.FileEditTool import EditTool
from claude_code_thy.tools.FileReadTool import ReadTool
from claude_code_thy.tools.FileWriteTool import WriteTool
from claude_code_thy.tools.GlobTool import GlobTool
from claude_code_thy.tools.GrepTool import GrepTool
from claude_code_thy.tools.ListMcpResourcesTool import ListMcpResourcesTool
from claude_code_thy.tools.ReadMcpResourceTool import ReadMcpResourceTool
from claude_code_thy.tools.SkillTool import SkillTool


def build_builtin_tools() -> list[Tool]:
    """构建 `builtin_tools`。"""
    return [
        AgentTool(),
        BashTool(),
        ReadTool(),
        EditTool(),
        WriteTool(),
        GlobTool(),
        GrepTool(),
        SkillTool(),
        ListMcpResourcesTool(),
        ReadMcpResourceTool(),
    ]
