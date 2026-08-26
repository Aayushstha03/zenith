import json
from pathlib import Path


ROOT = Path(__file__).parent
VAULT = ROOT / "fixtures" / "vault"


def test_fixture_manifest_and_markdown_shapes_exist() -> None:
    manifest = json.loads((ROOT / "fixtures" / "expected" / "manifest.json").read_text())
    daily = (VAULT / "logs" / "2026-08-20.md").read_text()
    project = (VAULT / "projects" / "News Resolution.md").read_text()
    kanban = (VAULT / "kanban" / "Kitchen App.md").read_text()

    assert manifest["logs/2026-08-20.md"]["sections"] == ["Work", "Thoughts", "Meals"]
    assert "## Thoughts\n#journal" in daily
    assert project.count("#### 2026-") == 2
    assert kanban.count("- [ ]") == 5
    assert kanban.count("- [x]") == 1
    assert "**Complete**" in kanban
    assert "kanban:settings" in kanban
    assert manifest["freeform/Oversized.md"]["oversized_section"] == "Migration Notes"
    assert manifest["freeform/Headless Long.md"]["entry_types"] == ["freeform_chunk"]


def test_fixture_inventory_covers_phase_one_contract() -> None:
    markdown_files = list(VAULT.rglob("*.md"))
    all_text = "\n".join(path.read_text() for path in markdown_files)
    assert len(markdown_files) >= 10
    for shape in (
        "[[Does Not Exist]]",
        "[[Shared]]",
        "#unregistered",
        "https://example.test/page#fragment",
        "{invalid json}",
        "Checked but still active",
        "Unchecked but in complete status",
        "saffron measurement",
        "Cardamom is the unique closing term",
    ):
        assert shape in all_text
