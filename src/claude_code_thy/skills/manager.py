from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from claude_code_thy.settings import SkillsSettings


@dataclass(slots=True)
class SkillDiscoveryResult:
    """记录一次路径扫描命中了哪些 skill 目录和触发规则。"""
    discovered_dirs: tuple[str, ...]
    matched_triggers: tuple[str, ...]


class SkillManager:
    """负责根据路径和配置规则发现本地 skill 目录。"""
    def __init__(self, workspace_root: Path, settings: SkillsSettings) -> None:
        """保存工作区根目录、skills 设置和已发现目录缓存。"""
        self.workspace_root = workspace_root
        self.settings = settings
        self._known_dirs: set[str] = set()

    def discover_for_paths(self, paths: list[Path]) -> SkillDiscoveryResult:
        """根据访问过的路径、父目录和触发规则补充可用 skill。"""
        if not self.settings.enabled:
            return SkillDiscoveryResult(discovered_dirs=(), matched_triggers=())

        discovered: set[str] = set()
        matched: set[str] = set()
        for path in paths:
            resolved = path.resolve()
            for parent in [resolved, *resolved.parents]:
                skill_file = parent / "SKILL.md"
                if skill_file.exists():
                    discovered.add(str(parent))
            relative = self._relative_path(resolved)
            for trigger in self.settings.triggers:
                if fnmatch.fnmatch(relative, trigger.pattern):
                    matched.add(trigger.pattern)
                    discovered.add(str((self.workspace_root / trigger.skill_dir).resolve()))

        for configured in self.settings.search_roots:
            root = (self.workspace_root / configured).resolve()
            if not root.exists():
                continue
            for skill_file in root.rglob("SKILL.md"):
                discovered.add(str(skill_file.parent.resolve()))

        self._known_dirs.update(discovered)
        return SkillDiscoveryResult(
            discovered_dirs=tuple(sorted(discovered)),
            matched_triggers=tuple(sorted(matched)),
        )

    def list_known_skills(self) -> tuple[str, ...]:
        """返回本次进程生命周期内已经发现过的 skill 目录。"""
        return tuple(sorted(self._known_dirs))

    def _relative_path(self, path: Path) -> str:
        """把绝对路径尽量转换成相对工作区的路径字符串。"""
        try:
            return str(path.relative_to(self.workspace_root))
        except ValueError:
            return str(path)
