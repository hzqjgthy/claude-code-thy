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
    command: PromptCommandSpec
    file_path: str


class SkillLoader:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self._cache: dict[tuple[str, str], tuple[int, SkillLoadResult]] = {}

    def load_from_skill_dir(self, skill_dir: Path) -> SkillLoadResult | None:
        skill_dir = skill_dir.resolve()
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None
        command_name = skill_dir.name
        return self._load_skill_file(
            skill_file,
            command_name=command_name,
            skill_root=skill_dir,
        )

    def load_from_skill_root(self, root_dir: Path) -> list[SkillLoadResult]:
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
        display_name = str(metadata.get("name") or "").strip() or None
        execution_context = "fork" if str(metadata.get("context", "")).strip().lower() == "fork" else "inline"
        command = PromptCommandSpec(
            name=command_name,
            description=description,
            kind="local_skill",
            loaded_from="skills",
            source="skills",
            content_length=len(content),
            content=content,
            arg_names=parse_string_list(metadata.get("arguments")),
            allowed_tools=parse_string_list(metadata.get("allowed-tools")),
            when_to_use=str(metadata.get("when-to-use") or metadata.get("when_to_use") or "").strip() or None,
            version=str(metadata.get("version") or "").strip() or None,
            model=str(metadata.get("model") or "").strip() or None,
            disable_model_invocation=parse_bool(metadata.get("disable-model-invocation"), default=False),
            user_invocable=parse_bool(metadata.get("user-invocable"), default=True),
            execution_context=execution_context,
            agent=str(metadata.get("agent") or "").strip() or None,
            effort=str(metadata.get("effort") or "").strip() or None,
            paths=parse_string_list(metadata.get("paths")),
            display_name=display_name,
            skill_root=str(skill_root),
            metadata={"file_path": str(skill_file)},
        )
        result = SkillLoadResult(command=command, file_path=str(skill_file))
        self._cache[cache_key] = (stat.st_mtime_ns, result)
        return result

    def _command_name_from_root(self, root_dir: Path, skill_dir: Path) -> str:
        relative = skill_dir.relative_to(root_dir)
        parts = [part for part in relative.parts if part]
        if not parts:
            return skill_dir.name
        return ":".join(parts)
