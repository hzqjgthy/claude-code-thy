from __future__ import annotations

import asyncio
import copy
from pathlib import Path

from claude_code_thy.mcp.names import (
    build_mcp_tool_name,
    is_normalized_mcp_name_match,
    matching_server_names,
    parse_dynamic_mcp_name,
)
from claude_code_thy.mcp.utils import run_async_sync
from claude_code_thy.models import SessionTranscript
from claude_code_thy.services import ToolServices, build_tool_services
from claude_code_thy.tools.MCPTool import MCPTool
from claude_code_thy.tools.McpAuthTool import McpAuthTool
from claude_code_thy.tools.selection import (
    selected_tools,
    tool_available_for_slash,
    tool_visible_for_model,
)
from claude_code_thy.tools.base import (
    PermissionContext,
    RuntimeSessionState,
    Tool,
    ToolContext,
    ToolError,
    ToolEventHandler,
    PermissionRequiredError,
    ToolResult,
    ToolSpec,
)

class ToolRuntime:
    """负责为每个会话解析、执行并动态扩展可用工具。"""
    def __init__(self, tools: list[Tool]) -> None:
        """注册内置工具，并为后续会话执行准备状态缓存。"""
        self._tools = {tool.name: tool for tool in tools}
        self._session_states: dict[str, RuntimeSessionState] = {}

    def list_tools(self) -> list[Tool]:
        """返回所有静态注册的内置工具。"""
        return [self._tools[name] for name in sorted(self._tools)]

    def list_tool_specs(self) -> list[ToolSpec]:
        """导出全部静态工具的 schema 描述。"""
        return [tool.to_spec() for tool in self.list_tools()]

    def list_tools_for_session(
        self,
        session: SessionTranscript,
        *,
        surface: str = "execution",
        allow_sync_refresh: bool = True,
    ) -> list[Tool]:
        """返回某个会话在指定面上真正可用的工具，包含动态 MCP 工具。"""
        tools = self._tools_by_name_for_session(
            session,
            allow_sync_refresh=allow_sync_refresh,
        )
        names = selected_tools(sorted(tools), surface=surface)
        return [tools[name] for name in names]

    def list_tool_specs_for_session(
        self,
        session: SessionTranscript,
        *,
        allow_sync_refresh: bool = True,
    ) -> list[ToolSpec]:
        """导出某个会话可见工具的完整 schema 列表。"""
        context = self._build_context(session, None)
        return [
            tool.to_spec_for_context(context)
            for tool in self.list_tools_for_session(
                session,
                surface="model",
                allow_sync_refresh=allow_sync_refresh,
            )
        ]

    async def warm_tool_specs_for_session(self, session: SessionTranscript) -> None:
        """在共享 MCP runner 上预热动态工具缓存，同时不阻塞当前事件循环。"""
        context = self._build_context(session, None)
        if context.services is None:
            return
        manager = context.services.mcp_manager
        if manager.cached_tools():
            return
        try:
            await asyncio.to_thread(
                run_async_sync,
                manager.refresh_all(),
            )
        except Exception:
            return

    def has_tool_for_session(
        self,
        session: SessionTranscript,
        tool_name: str,
        *,
        surface: str = "execution",
    ) -> bool:
        """判断某个工具名在当前会话指定面上是否可解析。"""
        tool = self._resolve_tool(session, tool_name)
        if tool is None:
            return False
        return self._tool_allowed(tool.name, surface=surface)

    def can_resolve_tool_for_session(self, session: SessionTranscript, tool_name: str) -> bool:
        """判断工具名在当前会话里是否真实存在，不考虑 model/slash 可见性。"""
        return self._resolve_tool(session, tool_name) is not None

    def services_for(self, session: SessionTranscript) -> ToolServices:
        """取回当前会话绑定的共享服务容器。"""
        context = self._build_context(session, None)
        if context.services is None:
            raise ToolError("工具服务未初始化")
        return context.services

    async def aclose(self) -> None:
        """关闭当前 runtime 持有的长连接服务，避免一次性进程退出时泄漏资源。"""
        seen: set[int] = set()
        for state in self._session_states.values():
            services = state.services
            if services is None:
                continue
            marker = id(services)
            if marker in seen:
                continue
            seen.add(marker)
            close_all = getattr(services.mcp_manager, "close_all", None)
            close_all_sync = getattr(services.mcp_manager, "close_all_sync", None)
            if callable(close_all_sync):
                try:
                    await asyncio.to_thread(close_all_sync)
                except Exception:
                    continue
                continue
            if close_all is None:
                continue
            try:
                await close_all()
            except Exception:
                continue

    def execute(
        self,
        tool_name: str,
        raw_args: str,
        session: SessionTranscript,
        *,
        surface: str = "execution",
        tool_use_id: str | None = None,
        event_handler: ToolEventHandler | None = None,
    ) -> ToolResult:
        """执行 slash 命令风格的工具调用，先把原始参数解析成结构化输入。"""
        tool = self._resolve_tool(session, tool_name)
        if tool is None:
            raise ToolError(f"未找到工具：{tool_name}")
        self._ensure_tool_allowed(tool.name, surface=surface)

        context = self._build_context(session, event_handler)
        input_data = tool.parse_raw_input(raw_args, context)
        return self._invoke(
            tool,
            input_data=input_data,
            session=session,
            tool_use_id=tool_use_id,
            event_handler=event_handler,
            original_input=input_data,
        )

    def execute_input(
        self,
        tool_name: str,
        input_data: dict[str, object],
        session: SessionTranscript,
        *,
        surface: str = "execution",
        tool_use_id: str | None = None,
        original_input: dict[str, object] | None = None,
        event_handler: ToolEventHandler | None = None,
    ) -> ToolResult:
        """直接执行结构化工具输入。"""
        tool = self._resolve_tool(session, tool_name)
        if tool is None:
            raise ToolError(f"未找到工具：{tool_name}")
        self._ensure_tool_allowed(tool.name, surface=surface)

        return self._invoke(
            tool,
            input_data=input_data,
            session=session,
            tool_use_id=tool_use_id,
            event_handler=event_handler,
            original_input=original_input,
        )

    def render_rejected(
        self,
        tool_name: str,
        input_data: dict[str, object],
        session: SessionTranscript,
        *,
        surface: str = "execution",
        reason: str,
        tool_use_id: str | None = None,
        original_input: dict[str, object] | None = None,
    ) -> ToolResult:
        """在用户拒绝权限确认后，生成统一的拒绝工具结果。"""
        tool = self._resolve_tool(session, tool_name)
        if tool is None:
            raise ToolError(f"未找到工具：{tool_name}")
        self._ensure_tool_allowed(tool.name, surface=surface)
        original = copy.deepcopy(original_input or input_data)
        user_modified = not tool.inputs_equivalent(original, input_data)
        context = self._build_context(
            session,
            None,
            tool_use_id=tool_use_id,
            invocation_input=copy.deepcopy(input_data),
            original_input=original,
            user_modified=user_modified,
        )
        result = tool.render_tool_use_rejected_message(
            copy.deepcopy(input_data),
            context,
            reason=reason,
            original_input=original,
            user_modified=user_modified,
        )
        self._finalize_result(tool, result, tool_use_id=tool_use_id)
        return result

    def _invoke(
        self,
        tool: Tool,
        *,
        input_data: dict[str, object],
        session: SessionTranscript,
        tool_use_id: str | None,
        event_handler: ToolEventHandler | None,
        original_input: dict[str, object] | None = None,
    ) -> ToolResult:
        """串起输入校验、权限判断、真正执行和结果收尾的完整流程。"""
        base_context = self._build_context(session, event_handler, tool_use_id=tool_use_id)
        original = copy.deepcopy(original_input or input_data)
        candidate = tool.validate_input_data(copy.deepcopy(input_data), base_context)
        validation = tool.validate_input(copy.deepcopy(candidate), base_context)
        if not validation.ok:
            raise ToolError(validation.message or f"工具 `{tool.name}` 输入校验失败")
        if validation.updated_input is not None:
            candidate = copy.deepcopy(validation.updated_input)

        permission_matcher = tool.prepare_permission_matcher(copy.deepcopy(candidate), base_context)
        permission_result = tool.check_permissions(copy.deepcopy(candidate), base_context)
        if permission_result.updated_input is not None:
            candidate = copy.deepcopy(permission_result.updated_input)

        user_modified = not tool.inputs_equivalent(original, candidate)
        context = self._build_context(
            session,
            event_handler,
            tool_use_id=tool_use_id,
            invocation_input=copy.deepcopy(candidate),
            original_input=original,
            user_modified=user_modified,
        )
        if permission_matcher is not None:
            context.emit(
                tool.name,
                "permission_matcher",
                "权限匹配器已准备",
                metadata={"tool_use_id": tool_use_id or "", "has_matcher": True},
            )

        if permission_result.behavior == "ask":
            request = permission_result.request
            if request is None:
                raise ToolError(f"工具 `{tool.name}` 返回了无效的权限确认结果")
            raise PermissionRequiredError(
                request,
                input_data=copy.deepcopy(candidate),
                original_input=original,
                user_modified=user_modified,
            )

        if permission_result.behavior == "deny":
            result = tool.render_tool_use_rejected_message(
                copy.deepcopy(candidate),
                context,
                reason=permission_result.reason,
                original_input=original,
                user_modified=user_modified,
            )
            self._finalize_result(tool, result, tool_use_id=tool_use_id)
            return result

        result = tool.execute_input(copy.deepcopy(candidate), context)
        if isinstance(result.structured_data, dict):
            result.structured_data.setdefault("user_modified", user_modified)
        result.metadata.setdefault("user_modified", user_modified)
        self._finalize_result(tool, result, tool_use_id=tool_use_id)
        return result

    def _finalize_result(
        self,
        tool: Tool,
        result: ToolResult,
        *,
        tool_use_id: str | None,
    ) -> None:
        """补齐模型回传内容和搜索文本等派生字段。"""
        result.tool_result_content = tool.map_tool_result_to_model_content(
            result,
            tool_use_id=tool_use_id,
        )
        search_text = tool.extract_search_text(result)
        if search_text.strip():
            result.metadata.setdefault("search_text", search_text)

    def _build_context(
        self,
        session: SessionTranscript,
        event_handler: ToolEventHandler | None,
        *,
        tool_use_id: str | None = None,
        invocation_input: dict[str, object] | None = None,
        original_input: dict[str, object] | None = None,
        user_modified: bool = False,
    ) -> ToolContext:
        """为一次工具调用组装上下文，并懒加载共享服务。"""
        cwd = Path(session.cwd).resolve()
        state = self._session_states.setdefault(session.session_id, RuntimeSessionState())
        if state.services is None:
            state.services = build_tool_services(cwd)
        state.services.register_session(session)
        state.approved_permissions = {
            str(item)
            for item in session.runtime_state.get("approved_permissions", [])
            if str(item).strip()
        }
        permission_context = PermissionContext(
            workspace_root=cwd,
            allow_roots=(cwd,),
            read_ignore_patterns=state.services.settings.read_ignore_patterns,
            permission_engine=state.services.permission_engine,
            sandbox_policy=state.services.sandbox_policy,
            approved_permissions=state.approved_permissions,
        )
        return ToolContext(
            session_id=session.session_id,
            cwd=cwd,
            state=state,
            permission_context=permission_context,
            services=state.services,
            emit_event=event_handler,
            tool_use_id=tool_use_id,
            invocation_input=invocation_input or {},
            original_input=original_input or {},
            user_modified=user_modified,
        )

    def _resolve_tool(self, session: SessionTranscript, tool_name: str) -> Tool | None:
        """先查静态工具，再按需解析动态 MCP 工具。"""
        tool = self._tools.get(tool_name)
        if tool is not None:
            return tool
        if tool_name.startswith("mcp__"):
            return self._resolve_mcp_tool(session, tool_name)
        return None

    def _tools_by_name_for_session(
        self,
        session: SessionTranscript,
        *,
        allow_sync_refresh: bool = True,
    ) -> dict[str, Tool]:
        """收集当前会话的静态和动态工具，并按工具名去重。"""
        dynamic = self._dynamic_tools_for_session(
            session,
            allow_sync_refresh=allow_sync_refresh,
        )
        tools = {tool.name: tool for tool in self.list_tools()}
        tools.update({tool.name: tool for tool in dynamic})
        return tools

    def _tool_allowed(self, tool_name: str, *, surface: str) -> bool:
        """按目标面判断工具是否允许使用。"""
        if surface == "model":
            return tool_visible_for_model(tool_name)
        return tool_available_for_slash(tool_name)

    def _ensure_tool_allowed(self, tool_name: str, *, surface: str) -> None:
        """在真正执行前校验工具是否允许出现在对应目标面。"""
        if self._tool_allowed(tool_name, surface=surface):
            return
        if surface == "model":
            raise ToolError(f"工具 `{tool_name}` 当前未暴露给主链模型")
        raise ToolError(f"工具 `{tool_name}` 当前未允许通过 slash 执行")

    def _resolve_mcp_tool(self, session: SessionTranscript, tool_name: str) -> Tool | None:
        """把 `/mcp__server__tool` 名称映射到具体 MCPTool 包装对象。"""
        context = self._build_context(session, None)
        if context.services is None:
            return None
        manager = context.services.mcp_manager
        server_name, normalized_tool_name = parse_dynamic_mcp_name(tool_name)
        if not server_name or not normalized_tool_name:
            return None

        configs_fn = getattr(manager, "configs", None)
        configs = configs_fn() if callable(configs_fn) else {}
        cached_tools = manager.cached_tools()
        available_servers = set(configs)
        available_servers.update(cached_tools)
        candidate_servers = matching_server_names(available_servers, server_name)
        for actual_name in candidate_servers:
            for definition in cached_tools.get(actual_name, []):
                if not is_normalized_mcp_name_match(definition.name, normalized_tool_name):
                    continue
                return self._wrap_mcp_definition(actual_name, definition)

        for actual_name in candidate_servers:
            try:
                definitions = run_async_sync(manager.list_tools(actual_name))
            except Exception:
                continue
            for definition in definitions:
                if not is_normalized_mcp_name_match(definition.name, normalized_tool_name):
                    continue
                return self._wrap_mcp_definition(actual_name, definition)
        return None

    def _dynamic_tools_for_session(
        self,
        session: SessionTranscript,
        *,
        allow_sync_refresh: bool = True,
    ) -> list[Tool]:
        """从 MCP 运行时快照中构造当前会话可见的动态工具列表。"""
        context = self._build_context(session, None)
        if context.services is None:
            return []
        manager = context.services.mcp_manager
        cached_tools = manager.cached_tools()
        if allow_sync_refresh and not cached_tools:
            try:
                run_async_sync(manager.refresh_all())
            except Exception:
                pass
            cached_tools = manager.cached_tools()
        dynamic_tools: list[Tool] = []
        for server_name, definitions in cached_tools.items():
            for definition in definitions:
                dynamic_tools.append(self._wrap_mcp_definition(server_name, definition))
        return dynamic_tools

    def _wrap_mcp_definition(self, server_name: str, definition) -> Tool:
        """把 MCP 返回的工具定义包装成本地 Tool 实例。"""
        if isinstance(getattr(definition, "annotations", None), dict) and definition.annotations.get("authTool"):
            return McpAuthTool(server_name)
        wrapped = MCPTool(server_name, definition)
        wrapped.name = build_mcp_tool_name(server_name, definition.name)
        return wrapped
