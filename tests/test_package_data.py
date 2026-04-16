from pathlib import Path


def test_stylesheet_file_exists_in_source_tree():
    stylesheet = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "claude_code_thy"
        / "ui"
        / "styles.tcss"
    )
    assert stylesheet.exists()
