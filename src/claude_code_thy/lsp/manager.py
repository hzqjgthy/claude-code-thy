from __future__ import annotations

import fnmatch
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from claude_code_thy.settings import LspServerSettings, LspSettings


LANGUAGE_IDS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".json": "json",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".css": "css",
    ".html": "html",
    ".rs": "rust",
    ".go": "go",
}


@dataclass(slots=True)
class LspNotification:
    method: str
    params: dict[str, object]


@dataclass(slots=True)
class _LspProcess:
    config: LspServerSettings
    root_dir: Path
    process: subprocess.Popen[bytes]
    next_id: int = 0


class LspManager:
    def __init__(self, workspace_root: Path, settings: LspSettings) -> None:
        self.workspace_root = workspace_root
        self.settings = settings
        self._servers: dict[tuple[str, str], _LspProcess] = {}

    def notify_file_opened(self, file_path: Path, content: str) -> None:
        self._notify(file_path, "textDocument/didOpen", self._open_params(file_path, content))

    def notify_file_changed(self, file_path: Path, content: str) -> None:
        self._notify(file_path, "textDocument/didChange", self._change_params(file_path, content))

    def notify_file_saved(self, file_path: Path) -> None:
        self._notify(file_path, "textDocument/didSave", self._save_params(file_path))

    def _notify(self, file_path: Path, method: str, params: dict[str, object]) -> None:
        if not self.settings.enabled:
            return

        server = self._select_server(file_path)
        if server is None:
            return

        process = self._server_process(server, file_path)
        if process is None or process.process.stdin is None:
            return

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        encoded = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        try:
            process.process.stdin.write(header + encoded)
            process.process.stdin.flush()
        except OSError:
            return

    def _select_server(self, file_path: Path) -> LspServerSettings | None:
        relative = self._relative_path(file_path)
        for server in self.settings.servers:
            for pattern in server.file_globs:
                if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(file_path.name, pattern):
                    return server
        return None

    def _server_process(self, server: LspServerSettings, file_path: Path) -> _LspProcess | None:
        root_dir = self._find_root(file_path, server)
        key = (server.name, str(root_dir))
        existing = self._servers.get(key)
        if existing is not None and existing.process.poll() is None:
            return existing

        try:
            process = subprocess.Popen(
                list(server.command),
                cwd=root_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return None

        wrapper = _LspProcess(config=server, root_dir=root_dir, process=process)
        self._servers[key] = wrapper
        self._initialize(wrapper)
        return wrapper

    def _initialize(self, wrapper: _LspProcess) -> None:
        params = {
            "processId": None,
            "rootUri": wrapper.root_dir.as_uri(),
            "capabilities": {},
        }
        self._send_request(wrapper, "initialize", params)
        self._send_notification(wrapper, "initialized", {})

    def _send_request(self, wrapper: _LspProcess, method: str, params: dict[str, object]) -> None:
        wrapper.next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": wrapper.next_id,
            "method": method,
            "params": params,
        }
        self._send_payload(wrapper, payload)

    def _send_notification(self, wrapper: _LspProcess, method: str, params: dict[str, object]) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._send_payload(wrapper, payload)

    def _send_payload(self, wrapper: _LspProcess, payload: dict[str, object]) -> None:
        if wrapper.process.stdin is None:
            return
        encoded = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        try:
            wrapper.process.stdin.write(header + encoded)
            wrapper.process.stdin.flush()
        except OSError:
            return

    def _find_root(self, file_path: Path, server: LspServerSettings) -> Path:
        if not server.root_markers:
            return self.workspace_root
        for parent in [file_path.parent, *file_path.parents]:
            for marker in server.root_markers:
                if (parent / marker).exists():
                    return parent
        return self.workspace_root

    def _relative_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workspace_root.resolve()))
        except ValueError:
            return str(path.resolve())

    def _language_id(self, file_path: Path, server: LspServerSettings) -> str:
        return server.language_id or LANGUAGE_IDS.get(file_path.suffix.lower(), "plaintext")

    def _open_params(self, file_path: Path, content: str) -> dict[str, object]:
        server = self._select_server(file_path)
        language_id = self._language_id(file_path, server) if server else "plaintext"
        return {
            "textDocument": {
                "uri": file_path.resolve().as_uri(),
                "languageId": language_id,
                "version": 1,
                "text": content,
            }
        }

    def _change_params(self, file_path: Path, content: str) -> dict[str, object]:
        return {
            "textDocument": {
                "uri": file_path.resolve().as_uri(),
                "version": 1,
            },
            "contentChanges": [{"text": content}],
        }

    def _save_params(self, file_path: Path) -> dict[str, object]:
        return {
            "textDocument": {
                "uri": file_path.resolve().as_uri(),
            }
        }
