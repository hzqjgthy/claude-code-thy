from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from claude_code_thy.permissions import PermissionDecision, PermissionEngine, PermissionRequest
    from claude_code_thy.sandbox import SandboxDecision, SandboxPolicy
    from claude_code_thy.services import ToolServices


class ToolError(RuntimeError):
    pass


class PermissionRequiredError(ToolError):
    def __init__(
        self,
        request: "PermissionRequest",
        *,
        input_data: dict[str, object] | None = None,
        original_input: dict[str, object] | None = None,
        user_modified: bool = False,
    ) -> None:
        self.request = request
        self.input_data = input_data or {}
        self.original_input = original_input or dict(self.input_data)
        self.user_modified = user_modified
        super().__init__(request.reason or f"{request.tool_name} 需要权限确认")


@dataclass(slots=True)
class FileReadState:
    content: str
    timestamp: int
    offset: int | None = None
    limit: int | None = None
    file_kind: str = "text"

    @property
    def is_full_file(self) -> bool:
        return self.limit is None and self.offset in (None, 1)

    @property
    def is_partial_view(self) -> bool:
        return not self.is_full_file


@dataclass(slots=True)
class RuntimeSessionState:
    read_file_state: dict[str, FileReadState] = field(default_factory=dict)
    services: ToolServices | None = None
    skill_dirs: set[str] = field(default_factory=set)
    touched_paths: set[str] = field(default_factory=set)
    approved_permissions: set[str] = field(default_factory=set)


@dataclass(slots=True)
class PermissionContext:
    workspace_root: Path
    allow_roots: tuple[Path, ...]
    read_ignore_patterns: tuple[str, ...] = ()
    permission_engine: PermissionEngine | None = None
    sandbox_policy: SandboxPolicy | None = None
    approved_permissions: set[str] = field(default_factory=set)

    def allows_path(self, path: Path) -> bool:
        if self.permission_engine is not None:
            decision = self.permission_engine.check_path("*", path)
            return decision.allowed and not decision.requires_confirmation
        for root in self.allow_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def check_path(self, tool_name: str, path: Path) -> PermissionDecision | None:
        if self.permission_engine is None:
            return None
        return self.permission_engine.check_path(tool_name, path)

    def require_path(self, tool_name: str, path: Path) -> None:
        decision = self.check_path(tool_name, path)
        if decision is None:
            if not self.allows_path(path):
                raise ToolError(f"路径超出允许范围：{path}")
            return
        if decision.allowed and not decision.requires_confirmation:
            return
        approval_key = self._approval_key(tool_name, "path", str(path.resolve()))
        if decision.requires_confirmation and approval_key in self.approved_permissions:
            return
        if decision.requires_confirmation:
            raise PermissionRequiredError(
                self._permission_request(
                    tool_name=tool_name,
                    target="path",
                    value=str(path.resolve()),
                    reason=decision.reason or f"{tool_name} 需要权限确认",
                    approval_key=approval_key,
                    decision=decision,
                )
            )
        raise ToolError(decision.reason or f"{tool_name} 被权限规则拒绝")

    def check_command(self, tool_name: str, command: str) -> PermissionDecision | None:
        if self.permission_engine is None:
            return None
        return self.permission_engine.check_command(tool_name, command)

    def require_command(self, tool_name: str, command: str) -> None:
        decision = self.check_command(tool_name, command)
        if decision is None:
            return
        if decision.allowed and not decision.requires_confirmation:
            return
        approval_key = self._approval_key(tool_name, "command", command)
        if decision.requires_confirmation and approval_key in self.approved_permissions:
            return
        if decision.requires_confirmation:
            raise PermissionRequiredError(
                self._permission_request(
                    tool_name=tool_name,
                    target="command",
                    value=command,
                    reason=decision.reason or f"{tool_name} 需要命令执行确认",
                    approval_key=approval_key,
                    decision=decision,
                )
            )
        raise ToolError(decision.reason or f"{tool_name} 命令被权限规则拒绝")

    def decide_sandbox(
        self,
        command: str,
        *,
        disable_requested: bool = False,
    ) -> SandboxDecision | None:
        if self.sandbox_policy is None:
            return None
        return self.sandbox_policy.decide_for_command(
            command,
            disable_requested=disable_requested,
        )

    def _approval_key(self, tool_name: str, target: str, value: str) -> str:
        return f"{tool_name}:{target}:{value}"

    def _permission_request(
        self,
        *,
        tool_name: str,
        target: str,
        value: str,
        reason: str,
        approval_key: str,
        decision: "PermissionDecision",
    ) -> "PermissionRequest":
        from claude_code_thy.permissions import PermissionRequest

        return PermissionRequest.create(
            tool_name=tool_name,
            target=target,
            value=value,
            reason=reason,
            approval_key=approval_key,
            matched_rule_pattern=(
                decision.matched_rule.pattern if decision.matched_rule is not None else ""
            ),
            matched_rule_description=(
                decision.matched_rule.description if decision.matched_rule is not None else ""
            ),
        )

    def build_request_for_path(
        self,
        tool_name: str,
        path: Path,
        *,
        reason: str = "",
    ) -> "PermissionRequest":
        decision = self.check_path(tool_name, path)
        normalized = str(path.resolve())
        return self._permission_request(
            tool_name=tool_name,
            target="path",
            value=normalized,
            reason=reason or (decision.reason if decision is not None else f"{tool_name} 需要权限确认"),
            approval_key=self._approval_key(tool_name, "path", normalized),
            decision=decision or self._default_decision(reason or f"{tool_name} 需要权限确认"),
        )

    def build_request_for_command(
        self,
        tool_name: str,
        command: str,
        *,
        reason: str = "",
    ) -> "PermissionRequest":
        decision = self.check_command(tool_name, command)
        return self._permission_request(
            tool_name=tool_name,
            target="command",
            value=command,
            reason=reason or (decision.reason if decision is not None else f"{tool_name} 需要命令执行确认"),
            approval_key=self._approval_key(tool_name, "command", command),
            decision=decision or self._default_decision(reason or f"{tool_name} 需要命令执行确认"),
        )

    def match_path_pattern(self, path: Path, pattern: str) -> bool:
        normalized = str(path.resolve())
        return fnmatch(normalized, pattern)

    def _default_decision(self, reason: str) -> "PermissionDecision":
        from claude_code_thy.permissions import PermissionDecision

        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason=reason,
        )


@dataclass(slots=True)
class ToolEvent:
    tool_name: str
    phase: str
    summary: str
    detail: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


ToolEventHandler = Callable[[ToolEvent], None]


@dataclass(slots=True)
class ToolContext:
    session_id: str
    cwd: Path
    state: RuntimeSessionState
    permission_context: PermissionContext
    services: ToolServices | None = None
    emit_event: ToolEventHandler | None = None
    tool_use_id: str | None = None
    invocation_input: dict[str, object] = field(default_factory=dict)
    original_input: dict[str, object] = field(default_factory=dict)
    user_modified: bool = False

    @property
    def read_file_state(self) -> dict[str, FileReadState]:
        return self.state.read_file_state

    @property
    def skill_dirs(self) -> set[str]:
        return self.state.skill_dirs

    @property
    def touched_paths(self) -> set[str]:
        return self.state.touched_paths

    def emit(
        self,
        tool_name: str,
        phase: str,
        summary: str,
        *,
        detail: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self.emit_event is None:
            return
        self.emit_event(
            ToolEvent(
                tool_name=tool_name,
                phase=phase,
                summary=summary,
                detail=detail,
                metadata=metadata or {},
            )
        )

    def discover_skills_for_paths(self, paths: list[Path]) -> tuple[str, ...]:
        if self.services is None:
            return ()
        result = self.services.skill_manager.discover_for_paths(paths)
        self.state.skill_dirs.update(result.discovered_dirs)
        self.state.touched_paths.update(str(path.resolve()) for path in paths)
        return result.discovered_dirs


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, object]
    read_only: bool = False
    concurrency_safe: bool = False
    search_behavior: dict[str, bool] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    ok: bool
    summary: str
    display_name: str = ""
    ui_kind: str = "text"
    output: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    preview: str = ""
    structured_data: dict[str, object] | list[object] | None = None
    tool_result_content: object | None = None

    def render(self) -> str:
        lines = [
            f"工具 `{self.tool_name}` {'执行成功' if self.ok else '执行失败'}",
            self.summary,
        ]

        for key, value in self.metadata.items():
            lines.append(f"{key}: {value}")

        if self.preview:
            lines.extend(["", "preview:", self.preview])

        if self.output:
            lines.extend(["", self.output])

        return "\n".join(lines)

    def content_for_model(self) -> object:
        if self.tool_result_content is not None:
            return self.tool_result_content
        return self.render()

    def message_metadata(self, *, tool_use_id: str | None = None) -> dict[str, object]:
        data = {
            "tool_name": self.tool_name,
            "display_name": self.display_name or self.tool_name,
            "ui_kind": self.ui_kind,
            "ok": self.ok,
            "summary": self.summary,
            "metadata": self.metadata,
            "preview": self.preview,
            "output": self.output,
        }
        if self.structured_data is not None:
            data["structured_data"] = self.structured_data
        if tool_use_id:
            data["tool_use_id"] = tool_use_id
        return data


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    message: str = ""
    updated_input: dict[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def allow(
        cls,
        *,
        updated_input: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> "ValidationResult":
        return cls(ok=True, updated_input=updated_input, metadata=metadata or {})

    @classmethod
    def reject(
        cls,
        message: str,
        *,
        updated_input: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> "ValidationResult":
        return cls(
            ok=False,
            message=message,
            updated_input=updated_input,
            metadata=metadata or {},
        )


PermissionBehavior = Literal["allow", "ask", "deny"]


@dataclass(slots=True)
class PermissionResult:
    behavior: PermissionBehavior
    reason: str = ""
    request: "PermissionRequest | None" = None
    updated_input: dict[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def allow(
        cls,
        *,
        updated_input: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> "PermissionResult":
        return cls(
            behavior="allow",
            updated_input=updated_input,
            metadata=metadata or {},
        )

    @classmethod
    def ask(
        cls,
        request: "PermissionRequest",
        *,
        updated_input: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> "PermissionResult":
        return cls(
            behavior="ask",
            reason=request.reason,
            request=request,
            updated_input=updated_input,
            metadata=metadata or {},
        )

    @classmethod
    def deny(
        cls,
        reason: str,
        *,
        updated_input: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> "PermissionResult":
        return cls(
            behavior="deny",
            reason=reason,
            updated_input=updated_input,
            metadata=metadata or {},
        )


class Tool(ABC):
    name: str
    description: str
    usage: str = ""
    input_schema: dict[str, object]

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        _ = (raw_args, context)
        raise ToolError(f"工具 `{self.name}` 不支持以字符串参数执行")

    @abstractmethod
    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        raise NotImplementedError

    @abstractmethod
    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        raise NotImplementedError

    def validate_input_data(self, input_data: dict[str, object], context: ToolContext) -> dict[str, object]:
        _ = context
        required = self.input_schema.get("required", [])
        if isinstance(required, list):
            missing = [name for name in required if name not in input_data]
            if missing:
                raise ToolError(f"tool input 缺少必填字段：{', '.join(str(name) for name in missing)}")

        properties = self.input_schema.get("properties", {})
        if isinstance(properties, dict):
            for name, spec in properties.items():
                if name not in input_data:
                    continue
                if not isinstance(spec, dict):
                    continue
                declared_type = spec.get("type")
                value = input_data[name]
                if value is None:
                    continue
                if declared_type == "string" and not isinstance(value, str):
                    raise ToolError(f"tool input 字段 `{name}` 必须是字符串")
                if declared_type == "integer" and not isinstance(value, int):
                    raise ToolError(f"tool input 字段 `{name}` 必须是整数")
                if declared_type == "boolean" and not isinstance(value, bool):
                    raise ToolError(f"tool input 字段 `{name}` 必须是布尔值")
                if declared_type == "array" and not isinstance(value, list):
                    raise ToolError(f"tool input 字段 `{name}` 必须是数组")
                if declared_type == "object" and not isinstance(value, dict):
                    raise ToolError(f"tool input 字段 `{name}` 必须是对象")
        return input_data

    def validate_input(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> ValidationResult:
        _ = context
        return ValidationResult.allow(updated_input=input_data)

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        _ = context
        return PermissionResult.allow(updated_input=input_data)

    def prepare_permission_matcher(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> Callable[[str], bool] | None:
        _ = (input_data, context)
        return None

    def inputs_equivalent(
        self,
        original_input: dict[str, object],
        updated_input: dict[str, object],
    ) -> bool:
        return original_input == updated_input

    def render_tool_use_rejected_message(
        self,
        input_data: dict[str, object],
        context: ToolContext,
        *,
        reason: str,
        original_input: dict[str, object] | None = None,
        user_modified: bool = False,
    ) -> ToolResult:
        _ = (context, original_input)
        summary = reason or f"{self.name} 被拒绝执行"
        return ToolResult(
            tool_name=self.name,
            ok=False,
            summary=summary,
            display_name=self.name,
            ui_kind="rejected",
            output=summary,
            metadata={
                "rejected": True,
                "user_modified": user_modified,
            },
            structured_data={
                "rejected": True,
                "reason": summary,
                "input": input_data,
                "user_modified": user_modified,
            },
            tool_result_content=f"Tool `{self.name}` was rejected: {summary}",
        )

    def map_tool_result_to_model_content(
        self,
        result: ToolResult,
        *,
        tool_use_id: str | None = None,
    ) -> object:
        _ = tool_use_id
        return result.content_for_model()

    def extract_search_text(self, result: ToolResult) -> str:
        if result.output.strip():
            return result.output
        if result.preview.strip():
            return result.preview
        if isinstance(result.structured_data, dict):
            if isinstance(result.structured_data.get("content"), str):
                return str(result.structured_data["content"])
            if isinstance(result.structured_data.get("filenames"), list):
                return "\n".join(str(item) for item in result.structured_data["filenames"])
        return ""

    def to_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            read_only=self.is_read_only(),
            concurrency_safe=self.is_concurrency_safe(),
            search_behavior=self.search_behavior(),
        )

    def to_spec_for_context(self, context: ToolContext | None = None) -> ToolSpec:
        _ = context
        return self.to_spec()

    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def search_behavior(self) -> dict[str, bool]:
        return {"is_search": False, "is_read": False}
