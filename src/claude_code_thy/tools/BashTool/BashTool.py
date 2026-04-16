from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Queue

from claude_code_thy.tools.base import PermissionRequiredError, PermissionResult, Tool, ToolContext, ToolError, ToolResult
from claude_code_thy.tools.shared.common import (
    MAX_RESULT_PREVIEW_CHARS,
    _build_diff,
    _decode_text,
    _display_path,
    _file_timestamp,
    _is_binary_bytes,
    _make_parser,
    _parse_args,
    _persist_output,
    _remember_read,
    _truncate,
)

from .command_semantics import interpret_command_result
from .constants import (
    EOF_SENTINEL,
    MAX_BASH_TIMEOUT_MS,
    MAX_INLINE_BASH_OUTPUT,
    MAX_PROGRESS_PREVIEW_LINES,
)
from .permissions import BashAssessment, enforce_bash_permissions
from .prompt import DESCRIPTION, USAGE
from .sed_parser import SedEditInfo, apply_sed_substitution
from .sed_validation import sed_command_is_allowed_by_allowlist
from .security import validate_bash_command
from .semantics import classify_shell_command, is_silent_shell_command


class BashTool(Tool):
    name = "bash"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to execute."},
            "timeout": {
                "type": "integer",
                "description": f"Optional timeout in milliseconds (max {MAX_BASH_TIMEOUT_MS}).",
            },
            "description": {"type": "string", "description": "Short human-readable description."},
            "run_in_background": {
                "type": "boolean",
                "description": "Whether to run the command in the background.",
            },
            "dangerouslyDisableSandbox": {
                "type": "boolean",
                "description": "Override destructive-command protection.",
            },
        },
        "required": ["command"],
    }

    def is_concurrency_safe(self) -> bool:
        return False

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        _ = context
        parser = _make_parser("bash", self.description)
        parser.add_argument("--timeout", type=int, default=30_000)
        parser.add_argument("--description")
        parser.add_argument("--background", action="store_true")
        parser.add_argument("--dangerously-disable-sandbox", action="store_true")

        if raw_args.startswith("-- "):
            arg_part = ""
            command = raw_args[3:]
        elif " -- " in raw_args:
            arg_part, command = raw_args.split(" -- ", 1)
        else:
            arg_part = ""
            command = raw_args

        args = _parse_args(parser, arg_part)
        command = command.strip()
        if not command:
            raise ToolError("命令不能为空")
        return {
            "command": command,
            "timeout": max(1, min(args.timeout, MAX_BASH_TIMEOUT_MS)),
            "description": args.description,
            "run_in_background": args.background,
            "dangerouslyDisableSandbox": args.dangerously_disable_sandbox,
        }

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        command = str(input_data.get("command", "")).strip()
        analysis = validate_bash_command(
            command,
            dangerous_disable_sandbox=bool(input_data.get("dangerouslyDisableSandbox", False)),
        )
        advanced_features: list[str] = []
        if analysis.has_heredoc:
            advanced_features.append("heredoc")
        if analysis.has_process_substitution:
            advanced_features.append("process substitution")
        if analysis.has_command_substitution:
            advanced_features.append("command substitution")
        if analysis.has_subshell:
            advanced_features.append("subshell")
        if analysis.has_function_definition:
            advanced_features.append("function definition")
        if advanced_features:
            return PermissionResult.ask(
                context.permission_context.build_request_for_command(
                    self.name,
                    command,
                    reason=(
                        "Advanced shell syntax requires approval: "
                        + ", ".join(advanced_features)
                    ),
                ),
                updated_input=input_data,
                metadata={"analysis": analysis.to_dict()},
            )
        try:
            enforce_bash_permissions(context, command)
        except PermissionRequiredError as error:
            return PermissionResult.ask(error.request, updated_input=input_data)
        except ToolError as error:
            return PermissionResult.deny(str(error), updated_input=input_data)
        return PermissionResult.allow(updated_input=input_data)

    def prepare_permission_matcher(self, input_data: dict[str, object], context: ToolContext):
        _ = context
        command = str(input_data.get("command", "")).strip()
        return lambda pattern: pattern == command or command.startswith(pattern.rstrip("*"))

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
        command = str(input_data.get("command", "")).strip()
        return ToolResult(
            tool_name=self.name,
            ok=False,
            summary=reason or "命令执行被拒绝",
            display_name="Bash",
            ui_kind="rejected",
            output=reason or "命令执行被拒绝。",
            metadata={
                "rejected": True,
                "command": command,
                "user_modified": user_modified,
            },
            structured_data={
                "command": command,
                "description": str(input_data.get("description") or command),
                "rejected": True,
                "user_modified": user_modified,
            },
            tool_result_content=f"Command was rejected: {reason or command}",
        )

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        args = self.parse_raw_input(raw_args, context)
        return self._run_command(
            context,
            command=str(args["command"]),
            timeout_ms=int(args.get("timeout", 30_000) or 30_000),
            description=str(args.get("description", "")).strip() or None,
            run_in_background=bool(args.get("run_in_background", False)),
            dangerously_disable_sandbox=bool(args.get("dangerouslyDisableSandbox", False)),
        )

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        command = str(input_data.get("command", "")).strip()
        if not command:
            raise ToolError("tool input 缺少 command")

        timeout_ms = int(input_data.get("timeout", 30_000) or 30_000)
        description = str(input_data.get("description", "")).strip() or None
        run_in_background = bool(input_data.get("run_in_background", False))
        dangerously_disable_sandbox = bool(input_data.get("dangerouslyDisableSandbox", False))
        return self._run_command(
            context,
            command=command,
            timeout_ms=max(1, min(timeout_ms, MAX_BASH_TIMEOUT_MS)),
            description=description,
            run_in_background=run_in_background,
            dangerously_disable_sandbox=dangerously_disable_sandbox,
        )

    def _run_command(
        self,
        context: ToolContext,
        *,
        command: str,
        timeout_ms: int,
        description: str | None,
        run_in_background: bool,
        dangerously_disable_sandbox: bool,
    ) -> ToolResult:
        assessment = enforce_bash_permissions(context, command)
        sandbox_decision = context.permission_context.decide_sandbox(
            command,
            disable_requested=dangerously_disable_sandbox,
        )
        sandbox_spec = None
        if context.services is not None and sandbox_decision is not None:
            profile_dir = context.services.task_manager.tasks_dir if run_in_background else None
            sandbox_spec = context.services.sandbox_manager.prepare_command(
                command,
                cwd=context.cwd,
                decision=sandbox_decision,
                profile_dir=profile_dir,
            )
        if context.services is not None:
            sandbox_error = context.services.sandbox_policy.validate_command(command)
            if sandbox_error is not None and not dangerously_disable_sandbox:
                raise ToolError(sandbox_error)
        analysis = validate_bash_command(
            command,
            dangerous_disable_sandbox=dangerously_disable_sandbox,
        )

        display_summary = description or command
        display_name = "Bash"
        semantics = classify_shell_command(command)
        command_kind = "command"
        if assessment.sed_edit is not None:
            command_kind = "edit"
        elif semantics["is_search"]:
            command_kind = "search"
        elif semantics["is_list"]:
            command_kind = "list"
        elif semantics["is_read"]:
            command_kind = "read"

        sed_before = self._prepare_sed_preview(context, assessment.sed_edit)

        if run_in_background:
            if context.services is None:
                raise ToolError("Background task manager is unavailable")
            task = context.services.task_manager.start_command(
                command=command,
                cwd=context.cwd,
                description=display_summary,
                launch_argv=(
                    sandbox_spec.argv if sandbox_spec is not None else ["/bin/bash", "-lc", command]
                ),
                launch_env=sandbox_spec.env if sandbox_spec is not None else None,
                task_kind="bash",
                sandbox_mode=sandbox_decision.mode if sandbox_decision is not None else None,
                sandbox_applied=sandbox_spec.sandbox_applied if sandbox_spec is not None else None,
                sandbox_reason=(
                    sandbox_spec.reason
                    if sandbox_spec is not None
                    else (sandbox_decision.reason if sandbox_decision is not None else "")
                ),
                cleanup_path=sandbox_spec.cleanup_path if sandbox_spec is not None else None,
                session_id=context.session_id,
                metadata={
                    "checked_paths": list(assessment.checked_paths),
                    "is_read_only": assessment.is_read_only,
                    **(
                        {"sed_edit_file": assessment.sed_edit.file_path}
                        if assessment.sed_edit is not None
                        else {}
                    ),
                },
            )
            summary = f"后台执行命令：{display_summary}"
            output = f"后台任务 {task.task_id} 已启动，输出写入 {task.output_path}"
            return ToolResult(
                tool_name=self.name,
                ok=True,
                summary=summary,
                display_name=display_name,
                ui_kind="bash",
                output=output,
                metadata={
                    "background_task_id": task.task_id,
                    "output_path": task.output_path,
                    "command_kind": command_kind,
                    "checked_paths": list(assessment.checked_paths),
                    "is_read_only": assessment.is_read_only,
                "timeout_ms": timeout_ms,
                "analysis_backend": analysis.backend,
                "analysis_warnings": list(analysis.warnings),
                "analysis_features": {
                    "has_subshell": analysis.has_subshell,
                    "has_command_substitution": analysis.has_command_substitution,
                    "has_process_substitution": analysis.has_process_substitution,
                    "has_heredoc": analysis.has_heredoc,
                    "has_function_definition": analysis.has_function_definition,
                    "max_nesting": analysis.max_nesting,
                },
                **self._sandbox_metadata(sandbox_decision, sandbox_spec),
                **(
                    {"sed_edit_file": assessment.sed_edit.file_path}
                        if assessment.sed_edit is not None
                        else {}
                    ),
                },
                structured_data={
                    "command": command,
                    "description": display_summary,
                    "background_task_id": task.task_id,
                    "output_path": task.output_path,
                    "command_kind": command_kind,
                    "checked_paths": list(assessment.checked_paths),
                    "is_read_only": assessment.is_read_only,
                    "no_output_expected": is_silent_shell_command(command),
                    **self._sandbox_metadata(sandbox_decision, sandbox_spec),
                    **(
                        {"sed_edit_file": assessment.sed_edit.file_path}
                        if assessment.sed_edit is not None
                        else {}
                    ),
                },
                tool_result_content=(
                    f"Command running in background with ID: {task.task_id}. "
                    f"Output is being written to: {task.output_path}"
                ),
            )

        start = time.time()
        context.emit(self.name, "running", f"运行命令：{display_summary}")
        launch_argv = (
            sandbox_spec.argv if sandbox_spec is not None else ["/bin/bash", "-lc", command]
        )
        launch_env = sandbox_spec.env if sandbox_spec is not None else None
        try:
            process = subprocess.Popen(
                launch_argv,
                cwd=context.cwd,
                env=launch_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            if sandbox_spec is not None and context.services is not None:
                context.services.sandbox_manager.cleanup_spec(sandbox_spec)
            raise ToolError(f"无法启动命令：{error}") from error

        stdout_queue: Queue[object] = Queue()

        def _reader() -> None:
            assert process.stdout is not None
            try:
                for line in iter(process.stdout.readline, ""):
                    stdout_queue.put(line)
            finally:
                stdout_queue.put(EOF_SENTINEL)

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        lines: list[str] = []
        last_progress_time = 0.0
        while True:
            elapsed_ms = int((time.time() - start) * 1000)
            if elapsed_ms > timeout_ms:
                process.kill()
                if sandbox_spec is not None and context.services is not None:
                    context.services.sandbox_manager.cleanup_spec(sandbox_spec)
                raise ToolError(f"命令执行超时（{timeout_ms}ms）")

            try:
                item = stdout_queue.get(timeout=0.2)
            except Empty:
                item = None

            if item is EOF_SENTINEL:
                break
            if isinstance(item, str):
                lines.append(item)

            now = time.time()
            if now - last_progress_time >= 0.6:
                preview = "".join(lines[-MAX_PROGRESS_PREVIEW_LINES:]).strip()
                context.emit(
                    self.name,
                    "progress",
                    f"运行命令：{display_summary}",
                    detail=preview,
                    metadata={
                        "elapsed_time_seconds": round(now - start, 1),
                        "total_lines": len(lines),
                        "timeout_ms": timeout_ms,
                    },
                )
                last_progress_time = now

            if item is None and process.poll() is not None:
                break

        return_code = process.wait()
        if sandbox_spec is not None and context.services is not None:
            context.services.sandbox_manager.cleanup_spec(sandbox_spec)

        combined_output = "".join(lines).strip()
        no_output_expected = is_silent_shell_command(command)
        semantic_result = interpret_command_result(command, return_code, combined_output, combined_output)

        persisted_output_path: Path | None = None
        if len(combined_output) > MAX_INLINE_BASH_OUTPUT:
            persisted_output_path = _persist_output(context, "bash-output", combined_output)
            preview_text = _truncate(combined_output, MAX_INLINE_BASH_OUTPUT)
            combined_output = f"{preview_text}\n\n[full output saved to {persisted_output_path}]"
        elif no_output_expected and not combined_output:
            combined_output = "Done"
        elif semantic_result["message"] and not combined_output:
            combined_output = str(semantic_result["message"])

        sandbox_violation = None
        if sandbox_spec is not None and sandbox_spec.sandbox_applied and context.services is not None:
            sandbox_violation = context.services.sandbox_manager.detect_violation(combined_output)

        preview = ""
        ui_kind = "bash"
        structured_data: dict[str, object] = {
            "command": command,
            "description": display_summary,
            "command_kind": command_kind,
            "full_output_path": str(persisted_output_path) if persisted_output_path else None,
            "checked_paths": list(assessment.checked_paths),
            "is_read_only": assessment.is_read_only,
            "no_output_expected": no_output_expected,
            "output_preview": _truncate(combined_output, MAX_RESULT_PREVIEW_CHARS),
            "analysis_backend": analysis.backend,
            "analysis_warnings": list(analysis.warnings),
            "analysis_features": {
                "has_subshell": analysis.has_subshell,
                "has_command_substitution": analysis.has_command_substitution,
                "has_process_substitution": analysis.has_process_substitution,
                "has_heredoc": analysis.has_heredoc,
                "has_function_definition": analysis.has_function_definition,
                "max_nesting": analysis.max_nesting,
            },
            **self._sandbox_metadata(sandbox_decision, sandbox_spec),
            **({"sandbox_violation": sandbox_violation} if sandbox_violation is not None else {}),
            **(
                {"sed_edit_file": assessment.sed_edit.file_path}
                if assessment.sed_edit is not None
                else {}
            ),
        }

        if sed_before is not None and not bool(semantic_result["is_error"]):
            sed_preview = self._finalize_sed_preview(context, sed_before)
            if sed_preview is not None:
                preview = str(sed_preview["preview"])
                display_name = "Update"
                ui_kind = "edit"
                structured_data = {
                    "type": "update",
                    "file_path": sed_preview["file_path"],
                    "diff_text": sed_preview["diff_text"],
                    "lines_added": sed_preview["lines_added"],
                    "lines_removed": sed_preview["lines_removed"],
                    "command": command,
                    "description": display_summary,
                    "command_kind": command_kind,
                    "checked_paths": list(assessment.checked_paths),
                    "is_read_only": assessment.is_read_only,
                    **self._sandbox_metadata(sandbox_decision, sandbox_spec),
                    **({"sandbox_violation": sandbox_violation} if sandbox_violation is not None else {}),
                }

        return ToolResult(
            tool_name=self.name,
            ok=not bool(semantic_result["is_error"]),
            summary=f"命令：{display_summary}",
            display_name=display_name,
            ui_kind=ui_kind,
            output=_truncate(combined_output, MAX_INLINE_BASH_OUTPUT + 512),
            metadata={
                "exit_code": return_code,
                "duration_ms": int((time.time() - start) * 1000),
                "command_kind": command_kind,
                "checked_paths": list(assessment.checked_paths),
                "is_read_only": assessment.is_read_only,
                "timeout_ms": timeout_ms,
                "no_output_expected": no_output_expected,
                "analysis_backend": analysis.backend,
                "analysis_warnings": list(analysis.warnings),
                "analysis_features": {
                    "has_subshell": analysis.has_subshell,
                    "has_command_substitution": analysis.has_command_substitution,
                    "has_process_substitution": analysis.has_process_substitution,
                    "has_heredoc": analysis.has_heredoc,
                    "has_function_definition": analysis.has_function_definition,
                    "max_nesting": analysis.max_nesting,
                },
                **self._sandbox_metadata(sandbox_decision, sandbox_spec),
                **(
                    {"persisted_output_path": str(persisted_output_path)}
                    if persisted_output_path is not None
                    else {}
                ),
                **(
                    {"return_code_interpretation": semantic_result["message"]}
                    if semantic_result["message"]
                    else {}
                ),
                **({"sandbox_violation": sandbox_violation} if sandbox_violation is not None else {}),
                **(
                    {"sed_edit_file": assessment.sed_edit.file_path}
                    if assessment.sed_edit is not None
                    else {}
                ),
            },
            preview=preview,
            structured_data=structured_data,
        )

    def _sandbox_metadata(self, decision, spec) -> dict[str, object]:
        if decision is None and spec is None:
            return {}
        data: dict[str, object] = {}
        if decision is not None:
            data.update(
                {
                    "sandbox_mode": decision.mode,
                    "sandboxed": decision.sandboxed,
                    "sandbox_reason": decision.reason,
                }
            )
        if spec is not None:
            data.update(
                {
                    "sandbox_requested": spec.sandbox_requested,
                    "sandbox_applied": spec.sandbox_applied,
                    "sandbox_adapter": spec.adapter,
                }
            )
            if spec.profile_path:
                data["sandbox_profile_path"] = spec.profile_path
            if spec.reason and "sandbox_reason" not in data:
                data["sandbox_reason"] = spec.reason
        return data

    def _prepare_sed_preview(
        self,
        context: ToolContext,
        sed_edit: SedEditInfo | None,
    ) -> dict[str, object] | None:
        if sed_edit is None:
            return None
        synthetic = (
            f"sed -i 's/{sed_edit.pattern}/{sed_edit.replacement}/{sed_edit.flags}' "
            f"{sed_edit.file_path}"
        )
        if not sed_command_is_allowed_by_allowlist(synthetic, allow_file_writes=True):
            return None

        path = Path(sed_edit.file_path)
        path = path if path.is_absolute() else context.cwd / path
        path = path.resolve(strict=False)
        if not path.exists() or path.is_dir():
            return None

        raw = path.read_bytes()
        if _is_binary_bytes(raw):
            return None

        original = _decode_text(raw)
        try:
            expected = apply_sed_substitution(original, sed_edit)
        except Exception:
            expected = original

        if context.services is not None:
            context.services.file_history.snapshot(path, original)

        return {
            "path": path,
            "original": original,
            "expected": expected,
        }

    def _finalize_sed_preview(
        self,
        context: ToolContext,
        sed_before: dict[str, object],
    ) -> dict[str, object] | None:
        path = sed_before["path"]
        if not isinstance(path, Path) or not path.exists() or path.is_dir():
            return None

        raw = path.read_bytes()
        if _is_binary_bytes(raw):
            return None
        updated = _decode_text(raw)
        original = sed_before["original"]
        if not isinstance(original, str) or updated == original:
            return None

        if context.services is not None:
            context.services.lsp_manager.notify_file_opened(path, updated)
            context.services.lsp_manager.notify_file_changed(path, updated)
            context.services.lsp_manager.notify_file_saved(path)

        _remember_read(
            context,
            path,
            updated,
            timestamp=_file_timestamp(path),
        )

        display_path = _display_path(path, context.cwd)
        patch = _build_diff(display_path, original, updated)
        return {
            "file_path": display_path,
            **patch,
        }
