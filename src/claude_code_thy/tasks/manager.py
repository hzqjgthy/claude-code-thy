from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from claude_code_thy.settings import TaskSettings
from claude_code_thy.tasks.registry import TaskRegistry
from claude_code_thy.tasks.types import BackgroundTask, TaskRecord, TaskStatus, TaskType, utc_now


class BackgroundTaskManager:
    def __init__(self, workspace_root: Path, settings: TaskSettings) -> None:
        self.workspace_root = workspace_root
        self.settings = settings
        self.tasks_dir = (workspace_root / settings.tasks_dir).resolve()
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.registry = TaskRegistry(self.tasks_dir, max_tasks=settings.max_background_tasks)

    def start_command(
        self,
        *,
        command: str,
        cwd: Path,
        description: str,
        task_type: TaskType = "local_bash",
        launch_argv: list[str] | None = None,
        launch_env: dict[str, str] | None = None,
        task_kind: str = "bash",
        tool_use_id: str | None = None,
        agent_id: str | None = None,
        sandbox_mode: str | None = None,
        sandbox_applied: bool | None = None,
        sandbox_reason: str = "",
        cleanup_path: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> BackgroundTask:
        merged_metadata = dict(metadata or {})
        if session_id:
            merged_metadata.setdefault("session_id", session_id)
        task_id = uuid4().hex[:12]
        output_path = self.tasks_dir / f"{task_id}.output"
        status_path = self.registry.path_for(task_id)
        task = BackgroundTask(
            task_id=task_id,
            task_type=task_type,
            description=description,
            cwd=str(cwd),
            output_path=str(output_path),
            status_path=str(status_path),
            status="running",
            command=command,
            task_kind=task_kind,
            tool_use_id=tool_use_id,
            agent_id=agent_id,
            sandbox_mode=sandbox_mode,
            sandbox_applied=sandbox_applied,
            sandbox_reason=sandbox_reason,
            metadata=merged_metadata,
        )
        self.registry.save(task)
        process = subprocess.Popen(
            [
                "/bin/bash",
                "-lc",
                self._background_wrapper(
                    task=task,
                    launch_argv=launch_argv or ["/bin/bash", "-lc", command],
                    launch_env=launch_env,
                    cleanup_path=cleanup_path,
                ),
            ],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        task.pid = process.pid
        self.registry.save(task)
        self.registry.trim()
        return task

    def start_local_agent(
        self,
        *,
        prompt: str,
        cwd: Path,
        model: str | None,
        env: dict[str, str] | None = None,
        description: str | None = None,
        session_id: str | None = None,
    ) -> BackgroundTask:
        command = f"agent-run: {prompt}"
        launch_argv = [*self._resolve_agent_launcher(), "--print"]
        if model:
            launch_argv.extend(["--model", model])
        launch_argv.append(prompt)
        return self.start_command(
            command=command,
            cwd=cwd,
            description=description or f"Agent: {prompt[:48]}",
            task_type="local_agent",
            launch_argv=launch_argv,
            launch_env=env,
            task_kind="agent",
            session_id=session_id,
            metadata={
                "prompt": prompt,
                "launcher": launch_argv[0] if launch_argv else "",
                **({"model": model} if model else {}),
            },
        )

    def create_task(
        self,
        *,
        task_type: TaskType,
        description: str,
        cwd: Path,
        metadata: dict[str, object] | None = None,
    ) -> TaskRecord:
        task_id = uuid4().hex[:12]
        task = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            description=description,
            cwd=str(cwd),
            output_path=str(self.tasks_dir / f"{task_id}.output"),
            status_path=str(self.registry.path_for(task_id)),
            status="pending",
            metadata=metadata or {},
        )
        self.registry.save(task)
        self.registry.trim()
        return task

    def update_task(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        return_code: int | None = None,
        metadata: dict[str, object] | None = None,
        finished: bool = False,
    ) -> TaskRecord | None:
        task = self.registry.load(task_id, BackgroundTask)
        if task is None:
            task = self.registry.load(task_id, TaskRecord)
        if task is None:
            return None
        if status is not None:
            task.status = status
        if return_code is not None:
            task.return_code = return_code
        if metadata:
            task.metadata.update(metadata)
        if finished:
            task.finished_at = utc_now()
        self.registry.save(task)
        return task

    def get(self, task_id: str) -> BackgroundTask | None:
        task = self.registry.load(task_id, BackgroundTask)
        if task is None:
            return None
        return self.refresh(task)

    def list_tasks(self) -> list[BackgroundTask]:
        tasks: list[BackgroundTask] = []
        for task_id in self.registry.list_ids():
            task = self.registry.load(task_id, BackgroundTask)
            if task is not None:
                tasks.append(self.refresh(task))
        tasks.sort(key=lambda item: item.started_at, reverse=True)
        return tasks

    def list_task_records(self) -> list[TaskRecord]:
        tasks: list[TaskRecord] = []
        for task_id in self.registry.list_ids():
            task = self.registry.load(task_id, BackgroundTask)
            if task is not None:
                tasks.append(self.refresh(task))
                continue
            record = self.registry.load(task_id, TaskRecord)
            if record is not None:
                tasks.append(record)
        tasks.sort(key=lambda item: item.started_at, reverse=True)
        return tasks

    def refresh(self, task: BackgroundTask) -> BackgroundTask:
        if task.status != "running" or task.pid is None:
            return task
        if self._pid_exists(task.pid):
            return task
        task.status = "exited"
        task.finished_at = task.finished_at or utc_now()
        self.registry.save(task)
        return task

    def read_output(self, task_id: str, *, tail_lines: int = 120) -> str | None:
        task = self.registry.load(task_id, BackgroundTask)
        if task is None:
            return None
        return self.registry.read_output(task.output_path, tail_lines=tail_lines)

    def stop_task(self, task_id: str) -> TaskRecord | None:
        task = self.registry.load(task_id, BackgroundTask)
        if task is None:
            task = self.registry.load(task_id, TaskRecord)
        if task is None:
            return None
        if task.pid is not None and task.status == "running":
            try:
                os.killpg(task.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass
        task.status = "killed"
        task.finished_at = utc_now()
        self.registry.save(task)
        return task

    def wait_for_task(
        self,
        task_id: str,
        *,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.2,
    ) -> TaskRecord | None:
        deadline = time.time() + max(0.0, timeout_seconds)
        while time.time() <= deadline:
            task = self.registry.load(task_id, BackgroundTask)
            if task is None:
                task = self.registry.load(task_id, TaskRecord)
            if task is None:
                return None
            if isinstance(task, BackgroundTask):
                task = self.refresh(task)
            if task.is_terminal:
                return task
            time.sleep(poll_interval)

        task = self.registry.load(task_id, BackgroundTask)
        if task is None:
            task = self.registry.load(task_id, TaskRecord)
        if isinstance(task, BackgroundTask):
            task = self.refresh(task)
        return task

    def _pid_exists(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _background_wrapper(
        self,
        *,
        task: BackgroundTask,
        launch_argv: list[str],
        launch_env: dict[str, str] | None,
        cleanup_path: str | None,
    ) -> str:
        output_path = shlex.quote(task.output_path)
        status_path = shlex.quote(task.status_path)
        python_bin = shlex.quote(sys.executable)
        command_line = shlex.join(launch_argv)
        env_prefix = ""
        if launch_env:
            env_prefix = " ".join(
                f"{key}={shlex.quote(value)}"
                for key, value in sorted(launch_env.items())
            )
        launch = f"{env_prefix} {command_line}".strip()
        cleanup_snippet = ""
        if cleanup_path:
            cleanup_snippet = f'rm -f {shlex.quote(cleanup_path)}\n'
        return f"""
set +e
{{
{launch}
}} > {output_path} 2>&1
rc=$?
{python_bin} - {status_path} "$rc" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
return_code = int(sys.argv[2])
try:
    data = json.loads(status_path.read_text(encoding="utf-8"))
except Exception:
    data = {{}}
data["return_code"] = return_code
data["status"] = "completed" if return_code == 0 else "failed"
data["finished_at"] = datetime.now(timezone.utc).isoformat()
status_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
PY
{cleanup_snippet}exit 0
""".strip()

    def _resolve_agent_launcher(self) -> list[str]:
        configured = os.environ.get("CLAUDE_CODE_THY_AGENT_LAUNCHER", "").strip()
        if configured:
            return shlex.split(configured)

        argv0 = Path(sys.argv[0]).expanduser()
        if argv0.name == "claude-code-thy" and argv0.exists():
            return [str(argv0.resolve())]

        found = shutil.which("claude-code-thy")
        if found:
            return [found]

        return [sys.executable, "-m", "claude_code_thy"]
