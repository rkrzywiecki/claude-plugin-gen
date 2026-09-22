from pathlib import Path

from generator.build import build
from generator.config_model import load_config

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"

MINIMAL_CONFIG = """
plugin:
  name: test-plugin
  version: 0.1.0
  description: A test plugin.
  author:
    name: Test Author
    email: test@example.com

agents:
  - id: reviewer
    description: Reviews code.
    tools: [Read, Grep]
    model: sonnet
    body: |
      You review code.

skills:
  - id: my-skill
    description: Does a thing.
    body: |
      Do the thing.

commands:
  - id: my-command
    description: Runs a thing.
    body: |
      Run the thing.

rules:
  - id: my-rule
    description: A rule.
    body: |
      Follow the rule.
"""


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "plugin.yaml"
    config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")
    return config_path


def test_build_writes_expected_files(tmp_path):
    config = load_config(_write_config(tmp_path))
    out_dir = tmp_path / "out"
    empty_static = tmp_path / "static"
    empty_static.mkdir()

    summary = build(config, TEMPLATES_DIR, empty_static, out_dir)

    assert (out_dir / "agents" / "reviewer.md").exists()
    assert (out_dir / "skills" / "my-skill" / "SKILL.md").exists()
    assert (out_dir / "commands" / "my-command.md").exists()
    assert (out_dir / "rules" / "my-rule.md").exists()
    assert (out_dir / ".claude-plugin" / "plugin.json").exists()
    assert (out_dir / ".claude-plugin" / "marketplace.json").exists()
    assert (out_dir / "CLAUDE.md").exists()
    assert (out_dir / "README.md").exists()
    assert (out_dir / "CHANGELOG.md").exists()
    # no hooks configured -> no hooks.json written
    assert not (out_dir / "hooks" / "hooks.json").exists()

    assert summary["agents"] == 1
    assert summary["skills"] == 1


def test_build_wipes_stale_output(tmp_path):
    config = load_config(_write_config(tmp_path))
    out_dir = tmp_path / "out"
    empty_static = tmp_path / "static"
    empty_static.mkdir()
    out_dir.mkdir()
    stale_file = out_dir / "stale.md"
    stale_file.write_text("leftover from a previous run", encoding="utf-8")

    build(config, TEMPLATES_DIR, empty_static, out_dir)

    assert not stale_file.exists()


def test_build_copies_skill_resource_files(tmp_path):
    config = load_config(_write_config(tmp_path))
    out_dir = tmp_path / "out"
    static_dir = tmp_path / "static"
    resource = static_dir / "skills" / "my-skill" / "scripts" / "helper.py"
    resource.parent.mkdir(parents=True)
    resource.write_text("print('hi')\n", encoding="utf-8")

    summary = build(config, TEMPLATES_DIR, static_dir, out_dir)

    copied = out_dir / "skills" / "my-skill" / "scripts" / "helper.py"
    assert copied.exists()
    assert copied.read_text(encoding="utf-8") == "print('hi')\n"
    assert summary["skills_with_resources"] == {"my-skill": ["scripts/helper.py"]}
