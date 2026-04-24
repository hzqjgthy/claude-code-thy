from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from claude_code_thy.settings import AppSettings, ToolPermissionRule


@dataclass(slots=True)
class PermissionDecision:
    """表示 `PermissionDecision`。"""
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""
    matched_rule: ToolPermissionRule | None = None


class PermissionEngine:
    """协调 `PermissionEngine`。"""
    def __init__(self, workspace_root: Path, settings: AppSettings) -> None:
        """初始化实例状态。"""
        self.workspace_root = workspace_root.resolve()
        self.settings = settings

    def check_path(self, tool_name: str, path: Path) -> PermissionDecision:
        """检查 `path`。"""
        normalized_path = str(path.resolve())
        matched = self._match_rule(tool_name, normalized_path, target="path")
        if matched is not None:
            return self._rule_to_decision(matched, normalized_path)

        try:
            path.resolve().relative_to(self.workspace_root)
        except ValueError:
            return PermissionDecision(
                allowed=False,
                reason=f"Path is outside workspace root: {normalized_path}",
            )

        return PermissionDecision(allowed=True)

    def check_command(self, tool_name: str, command: str) -> PermissionDecision:
        """检查 `command`。"""
        matched = self._match_rule(tool_name, command, target="command")
        if matched is not None:
            return self._rule_to_decision(matched, command)
        return PermissionDecision(allowed=True)

    def check_url(self, tool_name: str, url: str) -> PermissionDecision:
        """检查 URL 是否命中了浏览器相关的权限规则。"""
        matched = self._match_rule(tool_name, url, target="url")
        if matched is not None:
            return self._rule_to_decision(matched, url)
        return PermissionDecision(allowed=True)

    def _match_rule(self, tool_name: str, value: str, *, target: str) -> ToolPermissionRule | None:
        """匹配 `rule`。"""
        for rule in self.settings.permission_rules:
            if rule.target not in {target, "*"}:
                continue
            if rule.tool not in {tool_name, "*"}:
                continue
            if fnmatch.fnmatch(value, rule.pattern):
                return rule
        return None

    def _rule_to_decision(self, rule: ToolPermissionRule, value: str) -> PermissionDecision:
        """处理 `rule_to_decision`。"""
        effect = rule.effect.lower()
        if effect == "allow":
            return PermissionDecision(
                allowed=True,
                reason=rule.description or f"Allowed by rule: {rule.pattern}",
                matched_rule=rule,
            )
        if effect == "ask":
            return PermissionDecision(
                allowed=False,
                requires_confirmation=True,
                reason=rule.description or f"Requires confirmation: {value}",
                matched_rule=rule,
            )
        return PermissionDecision(
            allowed=False,
            reason=rule.description or f"Denied by rule: {rule.pattern}",
            matched_rule=rule,
        )
