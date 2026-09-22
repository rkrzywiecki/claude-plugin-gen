import pytest

from generator.config_model import ConfigError, load_config

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
"""


def test_loads_minimal_valid_config(tmp_path):
    config_path = tmp_path / "plugin.yaml"
    config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")

    config = load_config(config_path)

    assert config.meta.name == "test-plugin"
    assert config.meta.version == "0.1.0"
    assert len(config.agents) == 1
    assert config.agents[0].id == "reviewer"
    assert config.agents[0].body.endswith("\n")
    assert len(config.skills) == 1
    assert config.mcp_servers == []


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "does-not-exist.yaml")


def test_missing_required_field_raises(tmp_path):
    bad = MINIMAL_CONFIG.replace("  description: A test plugin.\n", "")
    config_path = tmp_path / "plugin.yaml"
    config_path.write_text(bad, encoding="utf-8")

    with pytest.raises(ConfigError, match="description"):
        load_config(config_path)


def test_duplicate_ids_raise(tmp_path):
    bad = MINIMAL_CONFIG + """
  - id: my-skill
    description: Duplicate id.
    body: |
      Oops.
"""
    config_path = tmp_path / "plugin.yaml"
    config_path.write_text(bad, encoding="utf-8")

    with pytest.raises(ConfigError, match="duplicate id"):
        load_config(config_path)


def test_hook_with_unknown_event_raises(tmp_path):
    bad = MINIMAL_CONFIG + """
hooks:
  - id: bad-hook
    event: NotARealEvent
    matcher: Bash
    description: Does something.
    script: bad-hook.sh
"""
    config_path = tmp_path / "plugin.yaml"
    config_path.write_text(bad, encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown event"):
        load_config(config_path)


def test_mcp_http_server_requires_url(tmp_path):
    bad = MINIMAL_CONFIG + """
mcp_servers:
  - id: broken
    enabled: false
    type: http
    description: Missing url.
"""
    config_path = tmp_path / "plugin.yaml"
    config_path.write_text(bad, encoding="utf-8")

    with pytest.raises(ConfigError, match="requires a 'url'"):
        load_config(config_path)
