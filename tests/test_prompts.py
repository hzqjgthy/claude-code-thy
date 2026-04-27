from claude_code_thy.models import SessionTranscript
from claude_code_thy.services import build_tool_services
import subprocess


def test_prompt_runtime_renders_context_and_keeps_skills_dynamic(tmp_path):
    """测试 prompt runtime 会渲染上下文，同时 skill 仍通过运行时自动发现。"""
    (tmp_path / "CLAUDE.md").write_text("# User rules\nAlways explain clearly.\n", encoding="utf-8")
    project_dir = tmp_path / ".claude-code-thy"
    project_dir.mkdir()
    (project_dir / "PROJECT_CONTEXT.md").write_text("Project context note.\n", encoding="utf-8")
    skill_dir = project_dir / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: Review a target\n"
        "---\n"
        "Please review carefully.\n",
        encoding="utf-8",
    )

    services = build_tool_services(tmp_path)
    session = SessionTranscript(
        session_id="s1",
        cwd=str(tmp_path),
        model="glm-4.5",
        provider_name="anthropic-compatible",
    )

    rendered = services.prompt_runtime.build_rendered_prompt(
        session,
        services,
        provider_name="anthropic-compatible",
        model="glm-4.5",
    )

    section_ids = [section.id for section in rendered.bundle.sections]
    assert "skill_usage" in section_ids
    assert "mcp_instructions" not in section_ids
    assert "skills_summary" not in section_ids
    assert "Skill 使用规则" in rendered.system_text
    assert "Always explain clearly." in rendered.user_context_text
    assert "Project context note." in rendered.user_context_text
    assert rendered.bundle.context_data.debug_meta["available_skill_names"] == ["review"]


def test_prompt_runtime_applies_workspace_override_and_disable(tmp_path):
    """测试工作区 override 和 disabled 目录会作用到 prompt 资源加载结果。"""
    prompt_root = tmp_path / ".claude-code-thy" / "prompts"
    override_dir = prompt_root / "overrides" / "sections"
    override_dir.mkdir(parents=True)
    (override_dir / "20_tool_usage.md").write_text(
        "---\n"
        "id: tool_usage\n"
        "order: 20\n"
        "target: system\n"
        "---\n"
        "OVERRIDDEN TOOL RULES\n",
        encoding="utf-8",
    )
    disabled_dir = prompt_root / "disabled"
    disabled_dir.mkdir(parents=True)
    (disabled_dir / "25_skill_usage.md").write_text("", encoding="utf-8")

    services = build_tool_services(tmp_path)
    session = SessionTranscript(
        session_id="s1",
        cwd=str(tmp_path),
        model="glm-4.5",
        provider_name="anthropic-compatible",
    )

    rendered = services.prompt_runtime.build_rendered_prompt(
        session,
        services,
        provider_name="anthropic-compatible",
        model="glm-4.5",
    )

    section_ids = [section.id for section in rendered.bundle.sections]
    assert "tool_usage" in section_ids
    assert "skill_usage" not in section_ids
    assert "OVERRIDDEN TOOL RULES" in rendered.system_text


def test_prompt_runtime_git_snapshot_is_summarized_and_keeps_unicode_paths(tmp_path):
    """测试 git snapshot 会降噪、隐藏未跟踪文件，并保留可读的 Unicode 路径。"""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)

    tracked = tmp_path / "中文文件.md"
    tracked.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "中文文件.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    tracked.write_text("v2\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("temp\n", encoding="utf-8")

    services = build_tool_services(tmp_path)
    session = SessionTranscript(
        session_id="s1",
        cwd=str(tmp_path),
        model="glm-4.5",
        provider_name="anthropic-compatible",
    )

    rendered = services.prompt_runtime.build_rendered_prompt(
        session,
        services,
        provider_name="anthropic-compatible",
        model="glm-4.5",
    )

    assert "Tracked changes: 1" in rendered.user_context_text
    assert "Changed files:" in rendered.user_context_text
    assert "中文文件.md" in rendered.user_context_text
    assert "untracked.txt" not in rendered.user_context_text
    assert "\\346" not in rendered.user_context_text
