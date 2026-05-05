import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bundled_runtime_matches_source_runtime():
    source = ROOT / "scripts" / "hermes_symphony.py"
    bundled = ROOT / ".hermes" / "skills" / "hermes-symphony" / "runtime" / "hermes_symphony.py"

    assert bundled.read_text() == source.read_text()


def test_install_hermes_skill_to_dest_dir(tmp_path: Path):
    dest_dir = tmp_path / "skills"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_hermes_skill.py"),
            "--dest-dir",
            str(dest_dir),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    installed = dest_dir / "hermes-symphony"

    assert "installed:" in result.stdout
    assert (installed / "SKILL.md").exists()
    assert (installed / "runtime" / "hermes_symphony.py").exists()
    assert (installed / "templates" / "task.yaml").exists()


def test_install_hermes_skill_dry_run(tmp_path: Path):
    dest_dir = tmp_path / "skills"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_hermes_skill.py"),
            "--dest-dir",
            str(dest_dir),
            "--dry-run",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "dry-run:" in result.stdout
    assert not (dest_dir / "hermes-symphony").exists()
