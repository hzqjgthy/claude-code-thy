from __future__ import annotations

import time

from claude_code_thy.tools.base import Tool, ToolContext, ToolError, ToolResult
from claude_code_thy.tools.shared.common import _make_parser, _parse_args, _truncate

from .prompt import DESCRIPTION, USAGE


DEFAULT_FOREGROUND_WAIT_MS = 120_000


class AgentTool(Tool):
    name = "agent"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Task prompt for the child agent."},
            "description": {"type": "string", "description": "Short human-readable task summary."},
            "model": {"type": "string", "description": "Optional model override."},
            "run_in_background": {
                "type": "boolean",
                "description": "Run in background and return immediately.",
            },
            "wait_timeout_ms": {
                "type": "integer",
                "description": "Foreground wait timeout before auto-backgrounding.",
            },
            "name": {"type": "string", "description": "Optional agent display name."},
        },
        "required": ["prompt"],
    }

    def is_concurrency_safe(self) -> bool:
        return False

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        _ = context
        parser = _make_parser("agent", self.description)
        parser.add_argument("--background", action="store_true")
        parser.add_argument("--model")
        parser.add_argument("--description")
        parser.add_argument("--wait-timeout-ms", type=int, default=DEFAULT_FOREGROUND_WAIT_MS)
        if raw_args.startswith("-- "):
            arg_part = ""
            prompt = raw_args[3:]
        elif " -- " in raw_args:
            arg_part, prompt = raw_args.split(" -- ", 1)
        else:
            arg_part = ""
            prompt = raw_args
        args = _parse_args(parser, arg_part)
        prompt = prompt.strip()
        if not prompt:
            raise ToolError("agent prompt 不能为空")
        return {
            "prompt": prompt,
            "description": args.description,
            "model": args.model,
            "run_in_background": args.background,
            "wait_timeout_ms": max(1, int(args.wait_timeout_ms or DEFAULT_FOREGROUND_WAIT_MS)),
        }

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        args = self.parse_raw_input(raw_args, context)
        return self.execute_input(args, context)

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        if context.services is None:
            raise ToolError("Background task manager is unavailable")

        prompt = str(input_data.get("prompt", "")).strip()
        if not prompt:
            raise ToolError("tool input 缺少 prompt")
        description = str(input_data.get("description", "")).strip() or f"Agent: {prompt[:48]}"
        model = str(input_data.get("model", "")).strip() or None
        run_in_background = bool(input_data.get("run_in_background", False))
        wait_timeout_ms = int(input_data.get("wait_timeout_ms", DEFAULT_FOREGROUND_WAIT_MS) or DEFAULT_FOREGROUND_WAIT_MS)

        task = context.services.task_manager.start_local_agent(
            prompt=prompt,
            cwd=context.cwd,
            model=model,
            env=None,
            description=description,
            session_id=context.session_id,
        )
        if run_in_background:
            return self._background_result(task.task_id, prompt, description, task.output_path, auto_backgrounded=False)

        start = time.time()
        last_preview = ""
        while True:
            task_state = context.services.task_manager.wait_for_task(
                task.task_id,
                timeout_seconds=1.0,
                poll_interval=0.2,
            )
            preview = context.services.task_manager.read_output(task.task_id, tail_lines=24) or ""
            preview = preview.strip()
            if preview and preview != last_preview:
                context.emit(
                    self.name,
                    "progress",
                    f"Agent running: {description}",
                    detail=_truncate(preview, 400),
                    metadata={"task_id": task.task_id},
                )
                last_preview = preview

            elapsed_ms = int((time.time() - start) * 1000)
            if task_state is not None and task_state.is_terminal:
                output = context.services.task_manager.read_output(task.task_id, tail_lines=200) or ""
                status = task_state.status
                ok = status == "completed"
                summary = f"Agent completed: {description}" if ok else f"Agent {status}: {description}"
                return ToolResult(
                    tool_name=self.name,
                    ok=ok,
                    summary=summary,
                    display_name="Agent",
                    ui_kind="agent",
                    output=_truncate(output or summary, 4000),
                    metadata={
                        "task_id": task.task_id,
                        "status": status,
                        "output_path": task.output_path,
                        **({"return_code": task_state.return_code} if task_state.return_code is not None else {}),
                    },
                    structured_data={
                        "status": status,
                        "task_id": task.task_id,
                        "prompt": prompt,
                        "description": description,
                        "output_path": task.output_path,
                        "output_preview": _truncate(output, 1200),
                    },
                    tool_result_content=_truncate(output or summary, 4000),
                )

            if elapsed_ms >= wait_timeout_ms:
                return self._background_result(
                    task.task_id,
                    prompt,
                    description,
                    task.output_path,
                    auto_backgrounded=True,
                )

    def _background_result(
        self,
        task_id: str,
        prompt: str,
        description: str,
        output_path: str,
        *,
        auto_backgrounded: bool,
    ) -> ToolResult:
        summary = "Agent running in background" if not auto_backgrounded else "Agent auto-backgrounded"
        output = (
            f"{summary}: {task_id}\n"
            f"description: {description}\n"
            f"output: {output_path}"
        )
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=summary,
            display_name="Agent",
            ui_kind="agent",
            output=output,
            metadata={
                "task_id": task_id,
                "status": "running",
                "output_path": output_path,
                "auto_backgrounded": auto_backgrounded,
            },
            structured_data={
                "status": "running",
                "task_id": task_id,
                "prompt": prompt,
                "description": description,
                "output_path": output_path,
                "auto_backgrounded": auto_backgrounded,
            },
            tool_result_content=(
                f"Agent task {task_id} is running in the background. "
                f"Output is available at {output_path}."
            ),
        )
