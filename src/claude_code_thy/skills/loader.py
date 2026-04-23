from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .frontmatter import (
    extract_description_from_markdown,
    parse_bool,
    parse_frontmatter_document,
    parse_string_list,
)
from .types import PromptCommandSpec


@dataclass(slots=True)
class SkillLoadResult:
    """保存解析后的 skill 命令对象以及它来自的文件路径。"""
    command: PromptCommandSpec
    file_path: str


class SkillLoader:
    """把本地 `SKILL.md` 解析成统一的 PromptCommandSpec。"""
    def __init__(self, workspace_root: Path) -> None:
        """记录工作区根目录，并准备按文件时间戳缓存解析结果。"""
        self.workspace_root = workspace_root.resolve()
        self._cache: dict[tuple[str, str], tuple[int, SkillLoadResult]] = {}

    def load_from_skill_root(self, root_dir: Path) -> list[SkillLoadResult]:
        """递归扫描一个 skills 根目录，加载其中所有 `SKILL.md`。"""
        root_dir = root_dir.resolve()
        if not root_dir.exists():
            return []
        results: list[SkillLoadResult] = []
        for skill_file in sorted(root_dir.rglob("SKILL.md")):
            command_name = self._command_name_from_root(root_dir, skill_file.parent)
            loaded = self._load_skill_file(
                skill_file.resolve(),
                command_name=command_name,
                skill_root=skill_file.parent.resolve(),
            )
            if loaded is not None:
                results.append(loaded)
        return results

    def _load_skill_file(
        self,
        skill_file: Path,
        *,
        command_name: str,
        skill_root: Path,
    ) -> SkillLoadResult | None:
        """读取并解析单个 skill 文件，同时复用基于 mtime 的缓存。"""
        try:
            stat = skill_file.stat()
        except OSError:
            return None

        cache_key = (str(skill_file), command_name)
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] == stat.st_mtime_ns:
            return cached[1]

        try:
            raw_text = skill_file.read_text(encoding="utf-8")
        except OSError:
            return None

        document = parse_frontmatter_document(raw_text)
        metadata = document.metadata
        content = document.content.strip()
        description = str(metadata.get("description") or "").strip() or extract_description_from_markdown(content)
        command = PromptCommandSpec(
            name=command_name,
            description=description,
            kind="local_skill",
            loaded_from="skills",
            source="skills",
            content_length=len(content),
            content=content,
            arg_names=parse_string_list(metadata.get("arguments")),
            version=str(metadata.get("version") or "").strip() or None,
            model=str(metadata.get("model") or "").strip() or None,
            disable_model_invocation=parse_bool(metadata.get("disable-model-invocation"), default=False),
            user_invocable=parse_bool(metadata.get("user-invocable"), default=True),
            skill_root=str(skill_root),
            metadata={"file_path": str(skill_file)},
        )
        result = SkillLoadResult(command=command, file_path=str(skill_file))
        self._cache[cache_key] = (stat.st_mtime_ns, result)
        return result

    def _command_name_from_root(self, root_dir: Path, skill_dir: Path) -> str:
        """把 skill 相对路径转换成冒号分隔的命令名。"""
        relative = skill_dir.relative_to(root_dir)
        parts = [part for part in relative.parts if part]
        if not parts:
            return skill_dir.name
        return ":".join(parts)
