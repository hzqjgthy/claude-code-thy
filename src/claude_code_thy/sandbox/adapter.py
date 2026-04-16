from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from claude_code_thy.sandbox.policy import SandboxDecision
from claude_code_thy.settings import SandboxSettings


SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"


@dataclass(slots=True)
class SandboxExecutionSpec:
    argv: list[str]
    env: dict[str, str] | None
    mode: str
    sandbox_requested: bool
    sandbox_applied: bool
    adapter: str
    reason: str = ""
    profile_path: str | None = None

    @property
    def cleanup_path(self) -> str | None:
        return self.profile_path


class SandboxManager:
    def __init__(self, workspace_root: Path, settings: SandboxSettings) -> None:
        self.workspace_root = workspace_root.resolve()
        self.settings = settings
        self._probe_result: tuple[bool, str] | None = None

    def prepare_command(
        self,
        command: str,
        *,
        cwd: Path,
        decision: SandboxDecision,
        profile_dir: Path | None = None,
    ) -> SandboxExecutionSpec:
        base_argv = ["/bin/bash", "-lc", command]
        if not decision.sandboxed:
            return SandboxExecutionSpec(
                argv=base_argv,
                env=None,
                mode=decision.mode,
                sandbox_requested=False,
                sandbox_applied=False,
                adapter="none",
                reason=decision.reason,
            )

        if not self._supports_sandbox_exec():
            _, reason = self._sandbox_probe_result()
            return SandboxExecutionSpec(
                argv=base_argv,
                env=None,
                mode=decision.mode,
                sandbox_requested=True,
                sandbox_applied=False,
                adapter="unavailable",
                reason=reason or "sandbox-exec 不可用，已回退为普通执行。",
            )

        profile_path = self._write_profile(
            cwd=cwd.resolve(),
            mode=decision.mode,
            profile_dir=profile_dir,
        )
        return SandboxExecutionSpec(
            argv=[SANDBOX_EXECUTABLE, "-f", str(profile_path), *base_argv],
            env=None,
            mode=decision.mode,
            sandbox_requested=True,
            sandbox_applied=True,
            adapter="sandbox-exec",
            reason=decision.reason,
            profile_path=str(profile_path),
        )

    def cleanup_spec(self, spec: SandboxExecutionSpec) -> None:
        if not spec.cleanup_path:
            return
        Path(spec.cleanup_path).unlink(missing_ok=True)

    def detect_violation(self, output: str) -> str | None:
        lowered = output.lower()
        if "sandbox_apply" in lowered:
            return "sandbox-exec 应用失败。"
        if "operation not permitted" in lowered:
            return "命令在 sandbox 中触发了受限操作。"
        if "sandbox violation" in lowered:
            return "命令触发了 sandbox violation。"
        return None

    def _supports_sandbox_exec(self) -> bool:
        if os.name != "posix" or shutil.which("sandbox-exec") is None:
            return False
        supported, _ = self._sandbox_probe_result()
        return supported

    def _sandbox_probe_result(self) -> tuple[bool, str]:
        if self._probe_result is not None:
            return self._probe_result
        try:
            result = subprocess.run(
                [
                    SANDBOX_EXECUTABLE,
                    "-p",
                    "(version 1)\n(allow default)\n",
                    "/usr/bin/true",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except OSError as error:
            self._probe_result = (False, f"sandbox-exec 启动失败：{error}")
            return self._probe_result
        except subprocess.TimeoutExpired:
            self._probe_result = (False, "sandbox-exec 探测超时，已回退为普通执行。")
            return self._probe_result

        if result.returncode == 0:
            self._probe_result = (True, "")
            return self._probe_result

        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        reason = stderr or stdout or f"sandbox-exec 返回非 0：{result.returncode}"
        self._probe_result = (False, f"sandbox-exec 当前不可用：{reason}")
        return self._probe_result

    def _write_profile(
        self,
        *,
        cwd: Path,
        mode: str,
        profile_dir: Path | None,
    ) -> Path:
        target_dir = profile_dir.resolve() if profile_dir is not None else None
        if target_dir is not None:
            target_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".sb",
            prefix="claude-code-thy-",
            dir=target_dir,
            delete=False,
        ) as handle:
            handle.write(self._profile_text(cwd=cwd, mode=mode))
            return Path(handle.name)

    def _profile_text(self, *, cwd: Path, mode: str) -> str:
        writable_roots = self._writable_roots(cwd=cwd, mode=mode)
        lines = [
            "(version 1)",
            "(allow default)",
        ]
        if not self.settings.allow_network:
            lines.append("(deny network*)")
        if mode in {"read-only", "workspace-write"}:
            lines.append("(deny file-write*)")
            for root in writable_roots:
                lines.append(f'(allow file-write* (subpath "{self._escape(root)}"))')
        return "\n".join(lines) + "\n"

    def _writable_roots(self, *, cwd: Path, mode: str) -> list[Path]:
        roots: list[Path] = []
        if mode == "workspace-write":
            roots.extend([self.workspace_root, cwd])
        roots.extend(
            Path(path).expanduser().resolve()
            for path in self.settings.writable_roots
            if path.strip()
        )
        temp_roots = {
            Path(tempfile.gettempdir()).resolve(),
            Path("/tmp").resolve(),
            Path("/private/tmp").resolve(),
            Path("/var/tmp").resolve(),
        }
        roots.extend(temp_roots)

        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            label = str(root)
            if label in seen:
                continue
            seen.add(label)
            unique.append(root)
        return unique

    def _escape(self, path: Path) -> str:
        return str(path).replace("\\", "\\\\").replace('"', '\\"')
