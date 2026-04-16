from __future__ import annotations


def tool_label() -> str:
    return "Write"


def summarize_input(raw_input: object) -> str:
    if not isinstance(raw_input, dict):
        return ""
    return str(raw_input.get("file_path", ""))


def extra_result_lines(metadata: dict[str, object]) -> list[str]:
    lines: list[str] = []
    if metadata.get("rejected"):
        lines.append("Rejected")
    if metadata.get("user_modified"):
        lines.append("User modified before approval")
    if metadata.get("encoding"):
        lines.append(f"Encoding: {metadata['encoding']}")
    structured = metadata.get("structured_data")
    if isinstance(structured, dict) and isinstance(structured.get("structured_patch"), list):
        lines.append(f"Hunks: {len(structured['structured_patch'])}")
        git_diff = structured.get("git_diff")
        if isinstance(git_diff, dict):
            lines.append(f"Git diff: +{git_diff.get('additions', 0)} -{git_diff.get('deletions', 0)}")
    return lines
