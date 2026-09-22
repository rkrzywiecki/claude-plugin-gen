"""
Import a single component (agent/skill/command/rule/hook) from a
markdown/shell file of any Claude Code plugin repo (e.g. one you cloned
locally) into THIS generator's config/plugin.yaml.

Doesn't modify the source - only reads the file and appends an entry to
the config. After importing you still need to run
`python generate.py --bump patch` for the change to actually land in the
generated repo under dist/.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from .security_scan import Finding, format_findings, scan_text


class ImportError_(Exception):
    """Bad import - with a readable message about what to fix. Named with a trailing
    underscore so it doesn't collide with the built-in ImportError."""


SECTION_BY_TYPE = {
    "agent": "agents",
    "skill": "skills",
    "command": "commands",
    "rule": "rules",
    "hook": "hooks",
}

_SKIP_NAMES = {".git", "__pycache__", ".DS_Store", ".pytest_cache"}


def _list_skill_resources(skill_dir: Path, skill_md_name: str) -> list[str]:
    """Lists every file in a skill's source directory other than SKILL.md itself
    (scripts/, references/, assets/, ...), relative to that directory. Read-only -
    used both for the --dry-run preview and to know what to actually copy.

    Rejects (raises ImportError_) any entry whose resolved real path escapes
    `skill_dir` - a symlink pointing outside the directory, or similar. This is
    a structural safety check, not a content heuristic, so unlike the security
    scan below it is never bypassable with --force.
    """
    if not skill_dir.is_dir():
        return []
    skill_dir_real = skill_dir.resolve()
    found: list[str] = []
    for item in sorted(skill_dir.rglob("*")):
        if item.is_dir():
            continue
        rel = item.relative_to(skill_dir)
        if rel.parts[0] == skill_md_name or rel.parts[0] in _SKIP_NAMES:
            continue
        if any(part in _SKIP_NAMES for part in rel.parts):
            continue
        item_real = item.resolve()
        if skill_dir_real not in item_real.parents and item_real != skill_dir_real:
            raise ImportError_(
                f"Refusing to import '{rel}': it resolves outside of {skill_dir} "
                f"(symlink or path escape) - this is never allowed, even with --force."
            )
        found.append(str(rel))
    return found


def _copy_skill_resources(skill_dir: Path, skill_md_name: str, dest_dir: Path) -> None:
    for rel in _list_skill_resources(skill_dir, skill_md_name):
        src = skill_dir / rel
        dst = dest_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Splits YAML frontmatter (--- ... ---) from the rest of the content. No
    frontmatter (typical for rules/ files in many plugins) -> empty dict + full content."""
    text = text.lstrip("﻿")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:]).lstrip("\n")
            try:
                fm = yaml.safe_load(fm_text) or {}
            except yaml.YAMLError as e:
                raise ImportError_(f"Could not parse frontmatter: {e}") from e
            if not isinstance(fm, dict):
                fm = {}
            return fm, body
    # no closing '---' found - treat the whole file as content
    return {}, text


def _scan_resource_files(base_dir: Path, rel_paths: list[str]) -> tuple[list[Finding], int]:
    """Runs the security scan over each resource file's content. Files that can't
    be decoded as UTF-8 (images, other binaries) are skipped and counted
    separately rather than scanned - pattern matching on binary data is not
    meaningful, but silently ignoring them would be misleading."""
    findings: list[Finding] = []
    binary_skipped = 0
    for rel in rel_paths:
        try:
            text = (base_dir / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            binary_skipped += 1
            continue
        for f in scan_text(text):
            f.file = rel
            findings.append(f)
    return findings, binary_skipped


def _enforce_security_findings(findings: list[Finding], source: str, dry_run: bool, force: bool) -> None:
    """Blocks the import (raises ImportError_) when findings exist and neither
    --dry-run nor --force applies. --dry-run only previews, so it never blocks -
    the caller still surfaces the findings to the user. --force is an explicit,
    logged override (see cmd_import), so it never blocks either."""
    if findings and not dry_run and not force:
        raise ImportError_(
            format_findings(findings, source)
            + "\n\nImport blocked. If this is a false positive, or you accept the risk, "
              "re-run with --force to import anyway (this will be logged as a warning)."
        )


def build_entry(
    component_type: str,
    source_path: Path,
    component_id: str | None,
    description: str | None,
    tools: list[str] | None,
    model: str | None,
    argument_hint: str | None,
    event: str | None,
    matcher: str | None,
    timeout: int,
    static_dir: Path,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if component_type not in SECTION_BY_TYPE:
        raise ImportError_(f"Unknown --type '{component_type}' (allowed: {', '.join(SECTION_BY_TYPE)})")

    if not source_path.exists():
        raise ImportError_(f"Source file does not exist: {source_path}")
    if source_path.is_dir():
        if component_type == "skill":
            # convenience: for --type skill people often pass the skill's directory, not SKILL.md directly
            candidate = source_path / "SKILL.md"
            if candidate.exists():
                source_path = candidate
            else:
                raise ImportError_(f"{source_path} is a directory with no SKILL.md - point at a specific file")
        else:
            files = sorted(p.name for p in source_path.glob("*") if p.is_file())
            hint = f" Files inside: {', '.join(files)}." if files else ""
            raise ImportError_(
                f"{source_path} is a directory, not a file - for --type {component_type} point at "
                f"a specific file inside it (e.g. one rule/agent/script).{hint}"
            )

    raw_text = source_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw_text)
    body = body.strip() + "\n"

    if component_type == "agent":
        entry_id = component_id or fm.get("name") or source_path.stem
        desc = description or fm.get("description")
        if not desc:
            raise ImportError_("Missing description - add it to the source's frontmatter or pass --description")
        entry_tools = tools if tools is not None else (fm.get("tools") or ["Read", "Grep", "Glob"])
        entry_model = model or fm.get("model") or "sonnet"
        return {"id": entry_id, "description": desc, "tools": entry_tools, "model": entry_model, "body": body}

    if component_type == "skill":
        entry_id = component_id or fm.get("name") or source_path.stem
        desc = description or fm.get("description")
        if not desc:
            raise ImportError_("Missing description - add it to the source's frontmatter or pass --description")
        # a skill directory can carry extra files (scripts/, references/, assets/, ...)
        # beside SKILL.md - find them here, scan them for security issues, then copy
        # them (unless --dry-run, and unless blocked) next to the generated SKILL.md
        # the same way `python generate.py` itself does (see build.py)
        resource_files = _list_skill_resources(source_path.parent, source_path.name)
        findings, binary_skipped = _scan_resource_files(source_path.parent, resource_files)
        _enforce_security_findings(findings, str(source_path.parent), dry_run, force)
        if resource_files and not dry_run:
            _copy_skill_resources(source_path.parent, source_path.name, static_dir / "skills" / entry_id)
        entry: dict[str, Any] = {"id": entry_id, "description": desc, "body": body}
        if resource_files:
            # informational only - popped off by the caller before the entry is saved to plugin.yaml
            entry["_resource_files_found"] = resource_files
            entry["_binary_resource_files_skipped"] = binary_skipped
        if findings:
            entry["_security_findings"] = findings
        return entry

    if component_type == "command":
        entry_id = component_id or source_path.stem
        desc = description or fm.get("description")
        if not desc:
            raise ImportError_("Missing description - add it to the source's frontmatter or pass --description")
        hint = argument_hint if argument_hint is not None else fm.get("argument-hint", "")
        return {"id": entry_id, "description": desc, "argument_hint": hint, "body": body}

    if component_type == "rule":
        entry_id = component_id or source_path.stem
        desc = description or fm.get("description")
        if not desc:
            raise ImportError_(
                "Rule files (rules/) in most plugins have no description in frontmatter - "
                "pass one with --description"
            )
        # if there was no frontmatter, body == raw_text; if there was (rare), use the content after it
        return {"id": entry_id, "description": desc, "body": body}

    if component_type == "hook":
        if not event:
            raise ImportError_("--event is required for --type hook (e.g. PreToolUse, PostToolUse)")
        if not matcher:
            raise ImportError_("--matcher is required for --type hook (e.g. Bash or 'Write|Edit')")
        entry_id = component_id or source_path.stem
        desc = description
        if not desc:
            # try to pull it from the first comment line in the script (skipping the shebang)
            for line in raw_text.splitlines()[:8]:
                line = line.strip()
                if line.startswith("#") and not line.startswith("#!"):
                    desc = line.lstrip("#").strip()
                    break
        if not desc:
            raise ImportError_("Missing description - pass --description (the script has no usable comment)")
        script_name = f"{entry_id}.sh"
        findings = scan_text(raw_text)
        for f in findings:
            f.file = source_path.name
        _enforce_security_findings(findings, str(source_path), dry_run, force)
        if not dry_run:
            hooks_dir = static_dir / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            dest = hooks_dir / script_name
            dest.write_text(raw_text, encoding="utf-8")
            dest.chmod(0o755)
        entry = {
            "id": entry_id, "event": event, "matcher": matcher,
            "description": desc, "script": script_name, "timeout": timeout,
        }
        if findings:
            entry["_security_findings"] = findings
        return entry

    raise ImportError_(f"Unknown type: {component_type}")  # pragma: no cover - guarded above


def append_entry(raw_config: dict, component_type: str, entry: dict[str, Any], force: bool) -> str:
    section = SECTION_BY_TYPE[component_type]
    items = raw_config.setdefault(section, [])
    existing_idx = next((i for i, it in enumerate(items) if it.get("id") == entry["id"]), None)
    if existing_idx is not None:
        if not force:
            raise ImportError_(
                f"{section}[{entry['id']}] already exists in the config - use --force to overwrite it"
            )
        items[existing_idx] = entry
        return "overwritten"
    items.append(entry)
    return "added"
