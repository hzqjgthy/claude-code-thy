from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4


@dataclass(slots=True)
class PermissionRequest:
    """保存 `PermissionRequest`。"""
    request_id: str
    tool_name: str
    target: str
    value: str
    reason: str = ""
    approval_key: str = ""
    matched_rule_pattern: str = ""
    matched_rule_description: str = ""

    @classmethod
    def create(
        cls,
        *,
        tool_name: str,
        target: str,
        value: str,
        reason: str = "",
        approval_key: str = "",
        matched_rule_pattern: str = "",
        matched_rule_description: str = "",
    ) -> "PermissionRequest":
        """创建 当前流程。"""
        return cls(
            request_id=uuid4().hex,
            tool_name=tool_name,
            target=target,
            value=value,
            reason=reason,
            approval_key=approval_key,
            matched_rule_pattern=matched_rule_pattern,
            matched_rule_description=matched_rule_description,
        )

    def to_dict(self) -> dict[str, object]:
        """转换为 `dict`。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PermissionRequest":
        """从 `dict` 构建结果。"""
        return cls(
            request_id=str(data.get("request_id", "")),
            tool_name=str(data.get("tool_name", "")),
            target=str(data.get("target", "")),
            value=str(data.get("value", "")),
            reason=str(data.get("reason", "")),
            approval_key=str(data.get("approval_key", "")),
            matched_rule_pattern=str(data.get("matched_rule_pattern", "")),
            matched_rule_description=str(data.get("matched_rule_description", "")),
        )

    @property
    def short_label(self) -> str:
        """处理 `short_label`。"""
        return f"{self.tool_name}:{self.target}"

    def prompt_text(self) -> str:
        """处理 `prompt_text`。"""
        action_map = {
            "command": "命令",
            "path": "路径",
            "url": "URL",
        }
        action = action_map.get(self.target, self.target or "目标")
        lines = [f"`{self.tool_name}` 请求访问{action}："]
        lines.append(self.value)
        if self.reason:
            lines.extend(["", f"原因：{self.reason}"])
        lines.extend(["", "回复 `yes` / `允许` 继续，或回复 `no` / `拒绝` 取消。"])
        return "\n".join(lines)
