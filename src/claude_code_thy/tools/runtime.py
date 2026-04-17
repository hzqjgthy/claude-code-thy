from __future__ import annotations

import copy
from pathlib import Path

from claude_code_thy.mcp.normalization import normalize_name_for_mcp
from claude_code_thy.mcp.string_utils import build_mcp_tool_name
from claude_code_thy.mcp.utils import run_async_sync
from claude_code_thy.models import SessionTranscript
from claude_code_thy.services import ToolServices, build_tool_services
from claude_code_thy.tools.MCPTool import MCPTool
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
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._session_states: dict[str, RuntimeSessionState] = {}

    def list_tools(self) -> list[Tool]:
        return [self._tools[name] for name in sorted(self._tools)]

    def list_tool_specs(self) -> list[ToolSpec]:
        return [tool.to_spec() for tool in self.list_tools()]

    def list_tools_for_session(self, session: SessionTranscript) -> list[Tool]:
        dynamic = self._dynamic_tools_for_session(session)
        tools = {tool.name: tool for tool in self.list_tools()}
        tools.update({tool.name: tool for tool in dynamic})
        return [tools[name] for name in sorted(tools)]

    def list_tool_specs_for_session(self, session: SessionTranscript) -> list[ToolSpec]:
        return [tool.to_spec() for tool in self.list_tools_for_session(session)]

    def has_tool_for_session(self, session: SessionTranscript, tool_name: str) -> bool:
        return self._resolve_tool(session, tool_name) is not None

    def services_for(self, session: SessionTranscript) -> ToolServices:
        context = self._build_context(session, None)
        if context.services is None:
            raise ToolError("工具服务未初始化")
        return context.services

    def execute(
        self,
        tool_name: str,
        raw_args: str,
        session: SessionTranscript,
        *,
        tool_use_id: str | None = None,
        event_handler: ToolEventHandler | None = None,
    ) -> ToolResult:
        tool = self._resolve_tool(session, tool_name)
        if tool is None:
            raise ToolError(f"未找到工具：{tool_name}")

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
        tool_use_id: str | None = None,
        original_input: dict[str, object] | None = None,
        event_handler: ToolEventHandler | None = None,
    ) -> ToolResult:
        tool = self._resolve_tool(session, tool_name)
        if tool is None:
            raise ToolError(f"未找到工具：{tool_name}")

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
        reason: str,
        tool_use_id: str | None = None,
        original_input: dict[str, object] | None = None,
    ) -> ToolResult:
        tool = self._resolve_tool(session, tool_name)
        if tool is None:
            raise ToolError(f"未找到工具：{tool_name}")
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
        cwd = Path(session.cwd).resolve()
        state = self._session_states.setdefault(session.session_id, RuntimeSessionState())
        if state.services is None:
            state.services = build_tool_services(cwd)
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
        tool = self._tools.get(tool_name)
        if tool is not None:
            return tool
        if tool_name.startswith("mcp__"):
            dynamic = self._resolve_mcp_tool(session, tool_name)
            if dynamic is not None:
                return dynamic
        for dynamic in self._dynamic_tools_for_session(session):
            if dynamic.name == tool_name:
                return dynamic
        return None

    def _resolve_mcp_tool(self, session: SessionTranscript, tool_name: str) -> Tool | None:
        context = self._build_context(session, None)
        if context.services is None:
            return None
        manager = context.services.mcp_manager
        server_name, normalized_tool_name = self._parse_mcp_tool_name(tool_name)
        if not server_name or not normalized_tool_name:
            return None

        configs_fn = getattr(manager, "configs", None)
        configs = configs_fn() if callable(configs_fn) else {}
        available_servers = set(configs)
        available_servers.update(manager.cached_tools())
        candidate_servers = [
            actual_name
            for actual_name in available_servers
            if normalize_name_for_mcp(actual_name) == server_name
        ]
        for actual_name in candidate_servers:
            for definition in manager.cached_tools().get(actual_name, []):
                if normalize_name_for_mcp(definition.name) != normalized_tool_name:
                    continue
                wrapped = MCPTool(actual_name, definition)
                wrapped.name = build_mcp_tool_name(actual_name, definition.name)
                return wrapped

        for actual_name in candidate_servers:
            try:
                definitions = run_async_sync(manager.list_tools(actual_name))
            except Exception:
                continue
            for definition in definitions:
                if normalize_name_for_mcp(definition.name) != normalized_tool_name:
                    continue
                wrapped = MCPTool(actual_name, definition)
                wrapped.name = build_mcp_tool_name(actual_name, definition.name)
                return wrapped
        return None

    def _parse_mcp_tool_name(self, tool_name: str) -> tuple[str, str]:
        if not tool_name.startswith("mcp__"):
            return "", ""
        suffix = tool_name[5:]
        if "__" not in suffix:
            return "", ""
        server_name, normalized_tool_name = suffix.split("__", 1)
        return server_name.strip(), normalized_tool_name.strip()

    def _dynamic_tools_for_session(self, session: SessionTranscript) -> list[Tool]:
        context = self._build_context(session, None)
        if context.services is None:
            return []
        manager = context.services.mcp_manager
        cached_tools = manager.cached_tools()
        if not cached_tools:
            try:
                run_async_sync(manager.refresh_all())
            except Exception:
                pass
            cached_tools = manager.cached_tools()
        dynamic_tools: list[Tool] = []
        for server_name, definitions in cached_tools.items():
            for definition in definitions:
                wrapped = MCPTool(server_name, definition)
                wrapped.name = build_mcp_tool_name(server_name, definition.name)
                dynamic_tools.append(wrapped)
        return dynamic_tools
