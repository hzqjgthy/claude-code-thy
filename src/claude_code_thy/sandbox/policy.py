from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from claude_code_thy.settings import SandboxSettings


@dataclass(slots=True)
class SandboxDecision:
    """表示一条命令最终是否应在沙箱中执行。"""
    mode: str
    sandboxed: bool
    reason: str = ""


class SandboxPolicy:
    """根据 settings 中的规则为命令生成沙箱决策。"""
    def __init__(self, settings: SandboxSettings) -> None:
        """保存沙箱相关设置。"""
        self.settings = settings

    def decide_for_command(
        self,
        command: str,
        *,
        disable_requested: bool = False,
    ) -> SandboxDecision:
        """综合禁用请求、排除规则和默认模式，给出最终执行策略。"""
        if disable_requested and not self.settings.allow_disable:
            return SandboxDecision(
                mode=self.settings.mode,
                sandboxed=True,
                reason="Sandbox override is disabled by settings.",
            )

        for pattern in self.settings.excluded_commands:
            if self._matches(pattern, command):
                return SandboxDecision(
                    mode="danger-full-access",
                    sandboxed=False,
                    reason=f"Excluded from sandbox by rule: {pattern}",
                )

        if disable_requested:
            return SandboxDecision(
                mode="danger-full-access",
                sandboxed=False,
                reason="Sandbox disabled by tool input.",
            )

        return SandboxDecision(
            mode=self.settings.mode,
            sandboxed=self.settings.mode != "danger-full-access",
            reason=f"Using sandbox mode: {self.settings.mode}",
        )

    def validate_command(self, command: str) -> str | None:
        """检查命令是否命中了危险命令规则。"""
        for pattern in self.settings.dangerous_commands:
            if self._matches(pattern, command):
                return f"Command matches dangerous sandbox rule: {pattern}"
        return None

    def _matches(self, pattern: str, command: str) -> bool:
        """同时支持 glob 匹配和前缀匹配两种规则写法。"""
        if not pattern:
            return False
        return fnmatch.fnmatch(command, pattern) or command.startswith(pattern)
