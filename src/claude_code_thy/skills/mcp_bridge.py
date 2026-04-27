from __future__ import annotations

import re

from claude_code_thy.mcp.names import build_prompt_command_name, normalize_name_for_mcp
from claude_code_thy.mcp.serializers import serialize_resource_read_result
from claude_code_thy.mcp.types import McpPromptDefinition, McpResourceDefinition

from .frontmatter import extract_description_from_markdown, parse_frontmatter_document, parse_string_list
from .types import PromptCommandSpec


def build_mcp_prompt_specs(
    server_name: str,
    prompts: list[McpPromptDefinition],
) -> list[PromptCommandSpec]:
    """把 MCP prompt 定义转换成统一的命令描述对象。"""
    return [
        PromptCommandSpec(
            name=build_prompt_command_name(server_name, prompt.name),
            description=prompt.description or f"MCP prompt from {server_name}",
            kind="mcp_prompt",
            loaded_from="mcp_prompt",
            source="mcp",
            content_length=0,
            user_invocable=True,
            disable_model_invocation=True,
            arg_names=tuple(prompt.arguments),
            server_name=server_name,
            original_name=prompt.name,
        )
        for prompt in prompts
    ]


def discover_mcp_skill_resources(
    resources: list[McpResourceDefinition],
) -> list[McpResourceDefinition]:
    """从资源列表中找出看起来像 skill 文档的 MCP 资源。"""
    discovered: list[McpResourceDefinition] = []
    for resource in resources:
        uri = resource.uri.lower()
        name = resource.name.lower()
        if uri.startswith("skill://") or uri.endswith("/skill.md") or name == "skill.md":
            discovered.append(resource)
    return discovered


def build_mcp_skill_spec(
    server_name: str,
    resource: McpResourceDefinition,
    result: object,
) -> PromptCommandSpec | None:
    """读取 MCP skill 资源内容，并按本地 skill 的同一套规则解析。"""
    output, structured = serialize_resource_read_result(result)
    content = _extract_skill_markdown(output, structured)
    if not content.strip():
        return None

    document = parse_frontmatter_document(content)
    metadata = document.metadata
    markdown = document.content.strip()
    skill_name = _skill_name_from_resource(resource)
    return PromptCommandSpec(
        name=f"{normalize_name_for_mcp(server_name)}:{skill_name}",
        description=str(metadata.get("description") or "").strip() or extract_description_from_markdown(markdown),
        kind="mcp_skill",
        loaded_from="mcp",
        source="mcp",
        content_length=len(markdown),
        content=markdown,
        arg_names=parse_string_list(metadata.get("arguments")),
        version=str(metadata.get("version") or "").strip() or None,
        model=str(metadata.get("model") or "").strip() or None,
        disable_model_invocation=str(metadata.get("disable-model-invocation", "")).strip().lower() == "true",
        user_invocable=str(metadata.get("user-invocable", "true")).strip().lower() != "false",
        server_name=server_name,
        original_name=resource.name,
        resource_uri=resource.uri,
        metadata={"resource_uri": resource.uri},
    )


def _extract_skill_markdown(output: str, structured: dict[str, object]) -> str:
    """优先从字符串输出中取 markdown，必要时回退到结构化 contents。"""
    if output.strip():
        return output
    contents = structured.get("contents")
    if not isinstance(contents, list):
        return ""
    for item in contents:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return str(item["text"])
    return ""


def _skill_name_from_resource(resource: McpResourceDefinition) -> str:
    """根据 skill URI 或资源名推导稳定的命令名后缀。"""
    uri = resource.uri
    if uri.startswith("skill://"):
        suffix = uri[len("skill://") :]
        parts = [part for part in re.split(r"[/:]+", suffix) if part]
        if parts:
            return normalize_name_for_mcp(parts[-1])
    name = resource.name.strip() or "skill"
    if name.lower() == "skill.md":
        parent = [part for part in re.split(r"[/:]+", resource.uri) if part]
        if parent:
            name = parent[-2] if len(parent) >= 2 else parent[-1]
    return normalize_name_for_mcp(name.replace(".md", ""))
