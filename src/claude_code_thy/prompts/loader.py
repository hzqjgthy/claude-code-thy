from __future__ import annotations

from pathlib import Path

from .frontmatter import parse_bool, parse_frontmatter_document, parse_string_list
from .types import PromptResource, PromptResourceKind


class PromptFileLoader:
    """负责从内置目录和工作区覆盖目录中加载 prompt markdown 资源。"""
    def __init__(self, workspace_root: Path) -> None:
        """记录工作区位置，并准备按文件 mtime 缓存解析结果。"""
        self.workspace_root = workspace_root.resolve()
        self.package_root = Path(__file__).resolve().parent
        self._cache: dict[str, tuple[int, PromptResource]] = {}

    def load_resources(
        self,
        kind: PromptResourceKind,
        *,
        provider_name: str | None = None,
    ) -> list[PromptResource]:
        """加载指定类别的 prompt 资源，并应用 override / append / disabled 规则。"""
        relative_dir = self._relative_dir_for_kind(kind)
        builtin_dir = self.package_root / relative_dir
        override_dir = self.workspace_root / ".claude-code-thy" / "prompts" / "overrides" / relative_dir
        append_dir = self.workspace_root / ".claude-code-thy" / "prompts" / "append" / relative_dir
        disabled_keys = self._load_disabled_keys()

        builtin_resources = {
            resource.relative_name: resource
            for resource in self._load_directory(
                builtin_dir,
                kind=kind,
                source_type="builtin",
                provider_name=provider_name,
            )
        }

        for relative_name, builtin in list(builtin_resources.items()):
            override_path = override_dir / relative_name
            if not override_path.exists() or not override_path.is_file():
                continue
            overridden = self._load_resource(
                override_path,
                kind=kind,
                source_type="override",
                relative_name=relative_name,
            )
            if overridden is not None and self._provider_matches(overridden, provider_name):
                builtin_resources[relative_name] = overridden
            else:
                builtin_resources[relative_name] = builtin

        appended = self._load_directory(
            append_dir,
            kind=kind,
            source_type="append",
            provider_name=provider_name,
        )
        resources = list(builtin_resources.values()) + appended
        filtered = [resource for resource in resources if not self._is_disabled(resource, disabled_keys)]
        return sorted(filtered, key=lambda item: (item.order, item.id, item.relative_name))

    def _relative_dir_for_kind(self, kind: PromptResourceKind) -> str:
        """返回一种资源类别在 prompts 包下的相对子目录。"""
        mapping = {
            "section": "sections",
            "template": "templates",
            "provider": "providers",
        }
        return mapping[kind]

    def _load_directory(
        self,
        root_dir: Path,
        *,
        kind: PromptResourceKind,
        source_type: str,
        provider_name: str | None,
    ) -> list[PromptResource]:
        """加载一个目录下的全部 markdown 文件。"""
        if not root_dir.exists():
            return []
        results: list[PromptResource] = []
        for file_path in sorted(root_dir.rglob("*.md")):
            relative_name = file_path.relative_to(root_dir).as_posix()
            resource = self._load_resource(
                file_path,
                kind=kind,
                source_type=source_type,
                relative_name=relative_name,
            )
            if resource is None or not self._provider_matches(resource, provider_name):
                continue
            results.append(resource)
        return results

    def _load_resource(
        self,
        file_path: Path,
        *,
        kind: PromptResourceKind,
        source_type: str,
        relative_name: str,
    ) -> PromptResource | None:
        """读取并解析单个 prompt markdown 文件。"""
        try:
            stat = file_path.stat()
        except OSError:
            return None

        cache_key = f"{kind}:{file_path.resolve()}"
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] == stat.st_mtime_ns:
            resource = cached[1]
            if resource.relative_name == relative_name and resource.source_type == source_type:
                return resource

        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except OSError:
            return None

        document = parse_frontmatter_document(raw_text)
        metadata = document.metadata
        content = document.content.strip()
        if not content:
            return None

        resource = PromptResource(
            id=str(metadata.get("id") or Path(relative_name).stem).strip(),
            kind=kind,
            target=self._parse_target(metadata.get("target")),
            order=self._parse_order(metadata.get("order"), fallback_name=Path(relative_name).stem),
            content=content,
            source_path=str(file_path.resolve()),
            source_type=source_type,
            relative_name=relative_name,
            cacheable=parse_bool(metadata.get("cacheable"), default=True),
            provider_name=self._normalize_provider_name(metadata.get("provider")),
            required_variables=self._parse_required_variables(metadata),
            metadata={
                str(key): value
                for key, value in metadata.items()
                if str(key) not in {"id", "target", "order", "cacheable", "provider", "required-variable", "required-variables"}
            },
        )
        self._cache[cache_key] = (stat.st_mtime_ns, resource)
        return resource

    def _parse_target(self, value: object) -> str:
        """把 frontmatter 中的 target 解析成 system / user。"""
        normalized = str(value or "system").strip().lower()
        if normalized == "user":
            return "user"
        return "system"

    def _parse_order(self, value: object, *, fallback_name: str) -> int:
        """优先读取 frontmatter order，缺失时回退到文件名前缀。"""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass
        prefix = fallback_name.split("_", 1)[0]
        try:
            return int(prefix)
        except ValueError:
            return 999

    def _parse_required_variables(self, metadata: dict[str, object]) -> tuple[str, ...]:
        """兼容 required-variable / required-variables 两种写法。"""
        raw = metadata.get("required-variables")
        if raw is None:
            raw = metadata.get("required-variable")
        return parse_string_list(raw)

    def _provider_matches(self, resource: PromptResource, provider_name: str | None) -> bool:
        """判断 provider 专属资源是否适用于当前 provider。"""
        if resource.kind != "provider":
            return True
        if provider_name is None:
            return True
        if resource.provider_name:
            return resource.provider_name == provider_name
        stem = Path(resource.relative_name).stem
        normalized_stem = self._normalize_provider_name(stem)
        return normalized_stem == provider_name

    def _normalize_provider_name(self, value: object) -> str | None:
        """把 provider 标识统一成项目内部 provider name。"""
        text = str(value or "").strip().lower()
        if not text:
            return None
        if text in {"anthropic", "anthropic-compatible"}:
            return "anthropic-compatible"
        if text in {"openai", "openai_responses", "openai-responses", "openai-responses-compatible"}:
            return "openai-responses-compatible"
        return text

    def _load_disabled_keys(self) -> set[str]:
        """读取工作区 disabled 目录中定义的禁用资源键。"""
        disabled_root = self.workspace_root / ".claude-code-thy" / "prompts" / "disabled"
        if not disabled_root.exists():
            return set()

        keys: set[str] = set()
        for file_path in disabled_root.rglob("*"):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(disabled_root).as_posix()
            keys.add(file_path.stem)
            keys.add(file_path.name)
            keys.add(relative)
            keys.add(relative.rsplit(".", 1)[0])
            try:
                text = file_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                keys.add(line)
        return keys

    def _is_disabled(self, resource: PromptResource, disabled_keys: set[str]) -> bool:
        """判断某个资源是否被工作区的 disabled 目录禁用。"""
        candidates = {
            resource.id,
            Path(resource.relative_name).stem,
            resource.relative_name,
            Path(resource.source_path).name,
        }
        return any(candidate in disabled_keys for candidate in candidates if candidate)
