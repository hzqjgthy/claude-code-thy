from pathlib import Path

import claude_code_thy.shells as shells


def test_resolve_bash_executable_prefers_git_bash_candidates_on_windows(tmp_path, monkeypatch):
    """Windows should fall back to common Git Bash locations before giving up."""
    fake_bash = tmp_path / "Git" / "bin" / "bash.exe"
    fake_bash.parent.mkdir(parents=True, exist_ok=True)
    fake_bash.write_text("", encoding="utf-8")

    monkeypatch.setattr(shells, "_is_windows", lambda: True)
    monkeypatch.setattr(shells, "_configured_bash_path", lambda: None)
    monkeypatch.setattr(shells.shutil, "which", lambda _: None)
    monkeypatch.setattr(shells, "_windows_bash_candidates", lambda: (fake_bash,))

    executable = shells.resolve_bash_executable()

    assert executable == str(fake_bash.resolve())
    assert shells.build_bash_command("echo hello") == [
        str(fake_bash.resolve()),
        "-lc",
        "echo hello",
    ]
