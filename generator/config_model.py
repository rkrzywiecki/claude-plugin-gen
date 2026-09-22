"""
Plugin configuration model + validation.

All plugin content (agents, skills, commands, hooks, rules, MCP servers)
lives in a single YAML file (config/plugin.yaml by default). This module
reads that file, checks that it is consistent (unique ids, required
fields) and returns plain objects that generator/build.py uses to render
the templates.

Deliberately without Pydantic - two dependencies (PyYAML + Jinja2) are
plenty for this project's scale, and the validation errors below are
arguably more readable for someone unfamiliar with Pydantic anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Invalid / inconsistent config/plugin.yaml - with a readable message about what to fix."""


@dataclass
class PluginMeta:
    name: str
    version: str
    description: str
    author_name: str
    author_email: str
    homepage: str = ""
    repository: str = ""
    license: str = "MIT"
    keywords: list[str] = field(default_factory=list)


@dataclass
class McpServer:
    id: str
    enabled: bool
    type: str          # "http" | "stdio"
    description: str
    url: str = ""       # for type == "http"
    command: str = ""   # for type == "stdio"
    args: list[str] = field(default_factory=list)


@dataclass
class Agent:
    id: str
    description: str
    tools: list[str]
    model: str
    body: str


@dataclass
class Skill:
    id: str
    description: str
    body: str


@dataclass
class Command:
    id: str
    description: str
    argument_hint: str
    body: str


@dataclass
class Rule:
    id: str
    description: str
    body: str


@dataclass
class Hook:
    id: str
    event: str          # PreToolUse | PostToolUse | ...
    matcher: str
    description: str
    script: str          # file name in static/hooks/, copied 1:1 to the output
    timeout: int = 30


@dataclass
class PluginConfig:
    meta: PluginMeta
    mcp_servers: list[McpServer]
    agents: list[Agent]
    skills: list[Skill]
    commands: list[Command]
    rules: list[Rule]
    hooks: list[Hook]
    raw: dict[str, Any] = field(default_factory=dict)


def _require(d: dict, key: str, ctx: str) -> Any:
    if key not in d or d[key] in (None, ""):
        raise ConfigError(f"{ctx}: missing required field '{key}'")
    return d[key]


def _check_unique_ids(items: list[dict], kind: str) -> None:
    seen: set[str] = set()
    for item in items:
        item_id = item.get("id")
        if not item_id:
            raise ConfigError(f"{kind}: entry without an 'id' field: {item!r}")
        if item_id in seen:
            raise ConfigError(f"{kind}: duplicate id '{item_id}' - id must be unique within its section")
        seen.add(item_id)


def load_config(path: Path) -> PluginConfig:
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    meta_raw = raw.get("plugin", {})
    meta = PluginMeta(
        name=_require(meta_raw, "name", "plugin"),
        version=_require(meta_raw, "version", "plugin"),
        description=_require(meta_raw, "description", "plugin"),
        author_name=_require(meta_raw.get("author", {}), "name", "plugin.author"),
        author_email=meta_raw.get("author", {}).get("email", ""),
        homepage=meta_raw.get("homepage", ""),
        repository=meta_raw.get("repository", ""),
        license=meta_raw.get("license", "MIT"),
        keywords=meta_raw.get("keywords", []),
    )

    mcp_raw = raw.get("mcp_servers", [])
    _check_unique_ids(mcp_raw, "mcp_servers")
    mcp_servers = []
    for m in mcp_raw:
        mtype = _require(m, "type", f"mcp_servers[{m.get('id')}]")
        if mtype == "http" and not m.get("url"):
            raise ConfigError(f"mcp_servers[{m['id']}]: type=http requires a 'url' field")
        if mtype == "stdio" and not m.get("command"):
            raise ConfigError(f"mcp_servers[{m['id']}]: type=stdio requires a 'command' field")
        mcp_servers.append(McpServer(
            id=m["id"],
            enabled=bool(m.get("enabled", False)),
            type=mtype,
            description=_require(m, "description", f"mcp_servers[{m['id']}]"),
            url=m.get("url", ""),
            command=m.get("command", ""),
            args=m.get("args", []),
        ))

    agents_raw = raw.get("agents", [])
    _check_unique_ids(agents_raw, "agents")
    agents = [
        Agent(
            id=a["id"],
            description=_require(a, "description", f"agents[{a['id']}]"),
            tools=a.get("tools", ["Read", "Grep", "Glob"]),
            model=a.get("model", "sonnet"),
            body=_require(a, "body", f"agents[{a['id']}]").strip() + "\n",
        )
        for a in agents_raw
    ]

    skills_raw = raw.get("skills", [])
    _check_unique_ids(skills_raw, "skills")
    skills = [
        Skill(
            id=s["id"],
            description=_require(s, "description", f"skills[{s['id']}]"),
            body=_require(s, "body", f"skills[{s['id']}]").strip() + "\n",
        )
        for s in skills_raw
    ]

    commands_raw = raw.get("commands", [])
    _check_unique_ids(commands_raw, "commands")
    commands = [
        Command(
            id=c["id"],
            description=_require(c, "description", f"commands[{c['id']}]"),
            argument_hint=c.get("argument_hint", ""),
            body=_require(c, "body", f"commands[{c['id']}]").strip() + "\n",
        )
        for c in commands_raw
    ]

    rules_raw = raw.get("rules", [])
    _check_unique_ids(rules_raw, "rules")
    rules = [
        Rule(
            id=r["id"],
            description=_require(r, "description", f"rules[{r['id']}]"),
            body=_require(r, "body", f"rules[{r['id']}]").strip() + "\n",
        )
        for r in rules_raw
    ]

    hooks_raw = raw.get("hooks", [])
    _check_unique_ids(hooks_raw, "hooks")
    valid_events = {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop"}
    hooks = []
    for h in hooks_raw:
        event = _require(h, "event", f"hooks[{h['id']}]")
        if event not in valid_events:
            raise ConfigError(f"hooks[{h['id']}]: unknown event '{event}' (allowed: {sorted(valid_events)})")
        hooks.append(Hook(
            id=h["id"],
            event=event,
            matcher=_require(h, "matcher", f"hooks[{h['id']}]"),
            description=_require(h, "description", f"hooks[{h['id']}]"),
            script=_require(h, "script", f"hooks[{h['id']}]"),
            timeout=int(h.get("timeout", 30)),
        ))

    return PluginConfig(
        meta=meta,
        mcp_servers=mcp_servers,
        agents=agents,
        skills=skills,
        commands=commands,
        rules=rules,
        hooks=hooks,
        raw=raw,
    )


class _NiceDumper(yaml.SafeDumper):
    """
    Two fixes relative to plain yaml.safe_dump:
      1. Multiline strings (body: ...) are written as a `|` block, not as a
         quoted string with \\n escapes and line wrapping - that's what
         PyYAML does by default, which turns a readable config into an
         unreadable one after a single `--bump`.
      2. List items (`- id: ...`) are indented 2 spaces under the parent
         key, matching the style this file is hand-written in - PyYAML's
         default Dumper leaves them at the same level as the key, which
         is valid YAML but inconsistent with the rest of the file.
    """


def _str_representer(dumper: yaml.Dumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_NiceDumper.add_representer(str, _str_representer)


def _increase_indent(self, flow=False, indentless=False):  # noqa: ANN001
    return yaml.SafeDumper.increase_indent(self, flow, False)


_NiceDumper.increase_indent = _increase_indent  # type: ignore[assignment]


def dump_config(raw: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(raw, f, Dumper=_NiceDumper, allow_unicode=True, sort_keys=False, width=88)
