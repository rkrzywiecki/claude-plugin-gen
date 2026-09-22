"""
Orchestrator: config/plugin.yaml -> a full plugin repo in the output directory.

Every run WIPES the output directory and regenerates it from scratch from
the config. That's a deliberate choice: the config is the single source of
truth, so there's no point "merging" an old and a new version of the
generated files - we just regenerate deterministically. Anything you don't
want to lose (notes, custom patches) shouldn't live in the generated repo -
it belongs in the config, or in a separate directory the generator ignores.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from .config_model import PluginConfig
from .render import make_env

STATIC_DIR_NAME = "static"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _agents_frontmatter_tools(tools: list[str]) -> str:
    return json.dumps(tools, ensure_ascii=False)


def _copy_skill_resources(static_dir: Path, skill_id: str, dest_dir: Path) -> list[str]:
    """Copies any extra files a skill needs (scripts/, references/, assets/, ...) from
    static/skills/<skill_id>/ next to the generated SKILL.md, preserving the directory
    structure and file permissions (so an executable script stays executable).

    This is convention-based, not something you declare in plugin.yaml: a skill's body
    can tell Claude to run e.g. `scripts/check_pending_migrations.py`, and as long as
    that file exists at static/skills/<skill_id>/scripts/check_pending_migrations.py it
    ends up right next to SKILL.md in the generated output. A skill with no such
    directory (the common case) is unaffected - this is a no-op for it.
    """
    src_dir = static_dir / "skills" / skill_id
    if not src_dir.is_dir():
        return []
    copied: list[str] = []
    for item in sorted(src_dir.rglob("*")):
        if item.is_dir():
            continue
        rel = item.relative_to(src_dir)
        dst = dest_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dst)  # copy2 preserves the mode bit, so a +x script stays +x
        copied.append(str(rel))
    return copied


def _copy_hook_resources(static_dir: Path, hook_id: str, dest_dir: Path) -> list[str]:
    """Copies any extra support files a hook's script needs (a shared Python module, a
    lookup/config file, ...) from static/hooks/<hook_id>/ into a subfolder next to the
    hook's own script in hooks/scripts/<hook_id>/. Same convention as skills, kept in a
    subfolder (rather than flat, like the main scripts) so two hooks' resource files
    never collide with each other in hooks/scripts/.

    A hook whose logic is fully self-contained in its one script (the common case) is
    unaffected - this only fires if static/hooks/<hook_id>/ actually exists. Reference
    these from the script itself relative to its own location, e.g. in bash:
    `dir=$(dirname "$0")/<hook_id>; python3 "$dir/helper.py"`.
    """
    src_dir = static_dir / "hooks" / hook_id
    if not src_dir.is_dir():
        return []
    copied: list[str] = []
    for item in sorted(src_dir.rglob("*")):
        if item.is_dir():
            continue
        rel = item.relative_to(src_dir)
        dst = dest_dir / hook_id / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dst)
        copied.append(f"{hook_id}/{rel}")
    return copied


def build(config: PluginConfig, templates_dir: Path, static_dir: Path, out_dir: Path) -> dict:
    """Generates the plugin repo. Returns a summary (counts) to print in the CLI."""

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    env = make_env(templates_dir)
    today = date.today().isoformat()

    # --- agents/ -------------------------------------------------------
    agent_tpl = env.get_template("agent.md.j2")
    for a in config.agents:
        content = agent_tpl.render(a=a, tools_json=_agents_frontmatter_tools(a.tools))
        _write(out_dir / "agents" / f"{a.id}.md", content)

    # --- skills/<id>/SKILL.md (+ any extra resource files) ---------------
    # Resources are copied first so the SKILL.md render below can mention them -
    # skills_with_resources keeps the full file lists (not just counts) so both
    # the generated SKILL.md and README.md/CLAUDE.md can name what's bundled,
    # letting someone installing the plugin see it, not just whoever imported it.
    skill_tpl = env.get_template("skill.md.j2")
    skills_with_resources: dict[str, list[str]] = {}
    for s in config.skills:
        skill_dir = out_dir / "skills" / s.id
        resources = _copy_skill_resources(static_dir, s.id, skill_dir)
        if resources:
            skills_with_resources[s.id] = resources
        content = skill_tpl.render(s=s, resources=resources)
        _write(skill_dir / "SKILL.md", content)

    # --- commands/ -------------------------------------------------------
    command_tpl = env.get_template("command.md.j2")
    for c in config.commands:
        content = command_tpl.render(c=c)
        _write(out_dir / "commands" / f"{c.id}.md", content)

    # --- rules/ -------------------------------------------------------
    rule_tpl = env.get_template("rule.md.j2")
    for r in config.rules:
        content = rule_tpl.render(r=r)
        _write(out_dir / "rules" / f"{r.id}.md", content)

    # --- hooks/ (hooks.json + copy the static scripts + any extra resources) ---
    hooks_with_resources: dict[str, list[str]] = {}
    if config.hooks:
        hooks_tpl = env.get_template("hooks.json.j2")
        by_event: dict[str, list] = {}
        for h in config.hooks:
            by_event.setdefault(h.event, []).append(h)
        content = hooks_tpl.render(by_event=by_event, plugin_name=config.meta.name)
        _write(out_dir / "hooks" / "hooks.json", content)

        scripts_dir = out_dir / "hooks" / "scripts"
        for h in config.hooks:
            src = static_dir / "hooks" / h.script
            if not src.exists():
                raise FileNotFoundError(
                    f"hooks[{h.id}]: script '{h.script}' does not exist in {static_dir / 'hooks'}"
                )
            dst = scripts_dir / h.script
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            dst.chmod(0o755)
            resources = _copy_hook_resources(static_dir, h.id, scripts_dir)
            if resources:
                hooks_with_resources[h.id] = resources

    # --- .mcp.json (enabled only) + docs/mcp-integrations.md (all of them) ---
    enabled_servers = [m for m in config.mcp_servers if m.enabled]
    if enabled_servers:
        mcp_tpl = env.get_template("mcp.json.j2")
        _write(out_dir / ".mcp.json", mcp_tpl.render(servers=enabled_servers))

    if config.mcp_servers:
        mcp_ref_tpl = env.get_template("mcp_reference.md.j2")
        _write(
            out_dir / "docs" / "mcp-integrations.md",
            mcp_ref_tpl.render(servers=config.mcp_servers),
        )

    # --- .claude-plugin/plugin.json + marketplace.json -------------------
    plugin_json_tpl = env.get_template("plugin.json.j2")
    _write(
        out_dir / ".claude-plugin" / "plugin.json",
        plugin_json_tpl.render(meta=config.meta, agents=config.agents),
    )

    marketplace_tpl = env.get_template("marketplace.json.j2")
    _write(
        out_dir / ".claude-plugin" / "marketplace.json",
        marketplace_tpl.render(meta=config.meta),
    )

    # --- CLAUDE.md + README.md -------------------------------------------
    claude_md_tpl = env.get_template("claude_md.j2")
    _write(
        out_dir / "CLAUDE.md",
        claude_md_tpl.render(meta=config.meta, agents=config.agents, skills=config.skills,
                              commands=config.commands, hooks=config.hooks, rules=config.rules,
                              skills_with_resources=skills_with_resources,
                              hooks_with_resources=hooks_with_resources),
    )

    readme_tpl = env.get_template("readme.md.j2")
    _write(
        out_dir / "README.md",
        readme_tpl.render(meta=config.meta, agents=config.agents, skills=config.skills,
                           commands=config.commands, hooks=config.hooks, rules=config.rules,
                           mcp_servers=config.mcp_servers, generated_on=today,
                           skills_with_resources=skills_with_resources,
                           hooks_with_resources=hooks_with_resources),
    )

    # --- CHANGELOG.md: append an entry for this version (append, don't overwrite) ---
    changelog_path = out_dir / "CHANGELOG.md"
    entry = (
        f"## {config.meta.version} — {today}\n\n"
        f"Generated from config/plugin.yaml: "
        f"{len(config.agents)} agents, {len(config.skills)} skills, "
        f"{len(config.commands)} commands, {len(config.hooks)} hooks, "
        f"{len(config.rules)} rules, {len(enabled_servers)}/{len(config.mcp_servers)} "
        f"MCP servers enabled.\n\n"
    )
    header = "# Changelog\n\nEntries appended automatically on every `python generate.py` run.\n\n"
    _write(changelog_path, header + entry)

    return {
        "agents": len(config.agents),
        "skills": len(config.skills),
        "commands": len(config.commands),
        "hooks": len(config.hooks),
        "rules": len(config.rules),
        "mcp_enabled": len(enabled_servers),
        "mcp_total": len(config.mcp_servers),
        "skills_with_resources": skills_with_resources,
        "hooks_with_resources": hooks_with_resources,
        "out_dir": str(out_dir),
        "version": config.meta.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
