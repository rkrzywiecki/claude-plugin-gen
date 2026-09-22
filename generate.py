#!/usr/bin/env python3
"""
Generator for your own Claude Code plugin, built from a single config/plugin.yaml file.

Two commands:

    python generate.py [options]
        -> generates dist/<plugin-name>/ from the current content of the
           config (this is the default command - it also works without
           passing the word "generate")

    python generate.py import --from <file> --type agent|skill|command|rule|hook --id <id>
        -> imports a SINGLE component from a markdown/shell file of another
           Claude Code plugin repo (e.g. one you cloned locally) into
           config/plugin.yaml - appends the entry, does not generate dist/ yet

Examples:
    python generate.py --bump patch
        -> bumps the version in config/plugin.yaml (0.1.0 -> 0.1.1), saves
           the config, and only then generates

    python generate.py import --from ~/other-plugin/agents/some-agent.md --type agent
        -> imports an agent 1:1 (id/description/tools/model from its frontmatter)

    python generate.py import --from ~/other-plugin/rules/java --type rule --id java-extra \\
        --description "Java rules imported from another plugin"
        -> many plugins keep rules as folders of files with no frontmatter, so
           the description has to be passed by hand

    python generate.py import --from ./my-hook.sh --type hook --id my-hook \\
        --event PreToolUse --matcher Bash --description "Blocks X"
        -> import a raw hook script (event/matcher can't be inferred from the
           script itself, so they're required)

How to add a new skill/agent/command BY HAND (without importing from another repo):
    1. Add a new entry to the relevant section of config/plugin.yaml
       (copy an existing one as a template - you need at least id, description, body).
    2. python generate.py --bump patch

Either way (import or manual edit), the new plugin version lands in
dist/<name>/ only after you run generation (`python generate.py`,
optionally with --bump) - `import` only prepares the config.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generator.build import build
from generator.config_model import ConfigError, dump_config, load_config
from generator.importer import SECTION_BY_TYPE, ImportError_, append_entry, build_entry
from generator.security_scan import format_findings

ROOT = Path(__file__).resolve().parent


def bump_version(version: str, part: str) -> str:
    try:
        major, minor, patch = (int(x) for x in version.split("."))
    except ValueError as exc:
        raise ConfigError(
            f"Can't bump version '{version}' - expected MAJOR.MINOR.PATCH format"
        ) from exc
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(part)


def cmd_generate(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="Generates a Claude Code plugin repo from config/plugin.yaml",
    )
    parser.add_argument("--config", default=str(ROOT / "config" / "plugin.yaml"),
                         help="path to the configuration file (default: config/plugin.yaml)")
    parser.add_argument("--out", default=None,
                         help="output directory (default: dist/<plugin-name>)")
    parser.add_argument("--bump", choices=["major", "minor", "patch"], default=None,
                         help="bump the version in the config before generating, and save the config")
    parser.add_argument("--dry-run", action="store_true",
                         help="only show what would be generated, write nothing")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    templates_dir = ROOT / "templates"
    static_dir = ROOT / "static"

    try:
        config = load_config(config_path)

        if args.bump:
            new_version = bump_version(config.meta.version, args.bump)
            print(f"[generate] version: {config.meta.version} -> {new_version}")
            config.raw["plugin"]["version"] = new_version
            dump_config(config.raw, config_path)
            config = load_config(config_path)  # reload so meta.version stays consistent

        out_dir = Path(args.out) if args.out else ROOT / "dist" / config.meta.name

        if args.dry_run:
            def _dirs_with_resources(kind: str, ids: list[str]) -> list[str]:
                base = static_dir / kind
                if not base.is_dir():
                    return []
                return sorted(i for i in ids if (base / i).is_dir())

            skills_with_resources_dry = _dirs_with_resources("skills", [s.id for s in config.skills])
            hooks_with_resources_dry = _dirs_with_resources("hooks", [h.id for h in config.hooks])

            print(f"[generate] DRY RUN - nothing written")
            print(f"  plugin: {config.meta.name} v{config.meta.version}")
            print(f"  agents: {len(config.agents)}")
            print(f"  skills: {len(config.skills)}"
                  + (f" ({len(skills_with_resources_dry)} with extra resource files: "
                     f"{', '.join(skills_with_resources_dry)})" if skills_with_resources_dry else ""))
            print(f"  commands: {len(config.commands)}")
            print(f"  hooks: {len(config.hooks)}"
                  + (f" ({len(hooks_with_resources_dry)} with extra resource files: "
                     f"{', '.join(hooks_with_resources_dry)})" if hooks_with_resources_dry else ""))
            print(f"  rules: {len(config.rules)}")
            print(f"  MCP servers: {len(config.mcp_servers)} "
                  f"({sum(1 for m in config.mcp_servers if m.enabled)} enabled)")
            print(f"  would generate to: {out_dir}")
            return 0

        summary = build(config, templates_dir, static_dir, out_dir)

    except ConfigError as exc:
        print(f"[generate] CONFIG ERROR: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"[generate] ERROR: {exc}", file=sys.stderr)
        return 1

    def _resource_note(with_resources: dict) -> str:
        if not with_resources:
            return ""
        return (f" ({len(with_resources)} with extra resource files: "
                f"{', '.join(f'{k} ({len(v)})' for k, v in with_resources.items())})")

    skills_note = _resource_note(summary.get("skills_with_resources", {}))
    hooks_note = _resource_note(summary.get("hooks_with_resources", {}))

    print(f"[generate] OK - {config.meta.name} v{summary['version']}")
    print(f"  agents:   {summary['agents']}")
    print(f"  skills:   {summary['skills']}{skills_note}")
    print(f"  commands: {summary['commands']}")
    print(f"  hooks:    {summary['hooks']}{hooks_note}")
    print(f"  rules:    {summary['rules']}")
    print(f"  MCP:      {summary['mcp_enabled']}/{summary['mcp_total']} enabled")
    print(f"  output:   {summary['out_dir']}")
    return 0


def cmd_import(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="generate.py import",
        description=(
            "Imports a SINGLE component (agent/skill/command/rule/hook) from a "
            "markdown/shell file of another Claude Code plugin repo (e.g. one you "
            "cloned locally) into config/plugin.yaml. Does not generate dist/ yet - "
            "run 'python generate.py --bump patch' afterwards."
        ),
    )
    parser.add_argument("--from", dest="source", required=True,
                         help="path to the source file (.md for agent/skill/command/rule, "
                              "for skill this can also be a directory containing SKILL.md; "
                              ".sh for hook)")
    parser.add_argument("--type", required=True, choices=list(SECTION_BY_TYPE),
                         help="which type of component this is")
    parser.add_argument("--id", default=None,
                         help="id in the config (default: frontmatter 'name', or the file name)")
    parser.add_argument("--description", default=None,
                         help="description - required if the source doesn't have one in frontmatter "
                              "(always required for --type rule and hook)")
    parser.add_argument("--tools", default=None,
                         help="--type agent only: comma-separated tool list, e.g. Read,Write,Bash")
    parser.add_argument("--model", default=None, help="--type agent only, e.g. sonnet")
    parser.add_argument("--argument-hint", dest="argument_hint", default=None,
                         help="--type command only")
    parser.add_argument("--event", default=None,
                         help="required for --type hook, e.g. PreToolUse or PostToolUse")
    parser.add_argument("--matcher", default=None,
                         help="required for --type hook, e.g. Bash or 'Write|Edit'")
    parser.add_argument("--timeout", type=int, default=30, help="--type hook only, in seconds")
    parser.add_argument("--config", default=str(ROOT / "config" / "plugin.yaml"))
    parser.add_argument("--force", action="store_true",
                         help="overwrite an existing entry with the same id, and bypass security-scan "
                              "blocking, instead of failing")
    parser.add_argument("--dry-run", action="store_true",
                         help="show what would be added, write nothing")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        raw = raw or {}

        tools = [t.strip() for t in args.tools.split(",")] if args.tools else None

        entry = build_entry(
            component_type=args.type,
            source_path=Path(args.source),
            component_id=args.id,
            description=args.description,
            tools=tools,
            model=args.model,
            argument_hint=args.argument_hint,
            event=args.event,
            matcher=args.matcher,
            timeout=args.timeout,
            static_dir=ROOT / "static",
            dry_run=args.dry_run,
            force=args.force,
        )
        resource_files = entry.pop("_resource_files_found", [])
        binary_skipped = entry.pop("_binary_resource_files_skipped", 0)
        findings = entry.pop("_security_findings", [])

        if args.dry_run:
            print(f"[import] DRY RUN - would add to section '{SECTION_BY_TYPE[args.type]}':\n")
            preview = {k: v for k, v in entry.items() if k != "body"}
            print(yaml.dump(preview, allow_unicode=True, sort_keys=False))
            body = entry.get("body", "")
            preview_lines = body.splitlines()[:6]
            print("body (first lines):")
            for line in preview_lines:
                print(f"  {line}")
            if len(body.splitlines()) > 6:
                print("  ...")
            if resource_files:
                print(f"\nwould also copy {len(resource_files)} resource file(s) into "
                      f"static/skills/{entry['id']}/: {', '.join(resource_files)}")
                if binary_skipped:
                    print(f"({binary_skipped} binary file(s) among them were not security-scanned)")
            if findings:
                print(f"\nSECURITY FINDINGS (would BLOCK a real import - use --force to override):")
                print(format_findings(findings, args.source))
            return 0

        if findings:
            # only reachable when --force was passed (otherwise build_entry already raised)
            print(f"[import] WARNING: security scan found issues, importing anyway because of --force:")
            print(format_findings(findings, args.source))

        status = append_entry(raw, args.type, entry, args.force)
        dump_config(raw, config_path)

    except (ImportError_, ConfigError) as exc:
        print(f"[import] ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"[import] OK - {status} '{entry['id']}' in section '{SECTION_BY_TYPE[args.type]}' ({config_path})")
    if resource_files:
        print(f"[import] also copied {len(resource_files)} resource file(s) into "
              f"static/skills/{entry['id']}/: {', '.join(resource_files)}")
        if binary_skipped:
            print(f"[import] ({binary_skipped} binary file(s) among them were not security-scanned)")
    print(f"[import] To generate dist/ with this change: python generate.py --bump patch")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "import":
        return cmd_import(argv[1:])
    return cmd_generate(argv)


if __name__ == "__main__":
    raise SystemExit(main())
