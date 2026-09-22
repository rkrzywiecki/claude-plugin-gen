# plugin-generator - java-spring-ops

A generator for your own Claude Code plugin dedicated to the Java/Spring
Boot + GitLab + GitLab CI + Jira + Docker/Compose + git stack. Instead of
hand-writing dozens of markdown files, the whole plugin lives in one file,
`config/plugin.yaml`, and `generate.py` renders a complete plugin repo from
it into `dist/java-spring-ops/`.

The full architecture and design decisions are written up in the document
you received alongside this archive ("Plan and architecture: a custom
Claude Code plugin"). This README is just a quick start.

## Quick start

```bash
pip install -r requirements.txt
python3 generate.py --dry-run   # preview, nothing written
python3 generate.py             # generates dist/java-spring-ops/
```

`dist/` is generated output and is git-ignored - it isn't part of this
repo. Run `python3 generate.py` once after cloning to produce
`dist/java-spring-ops/` locally.

## Installing the generated plugin in Claude Code

```
/plugin marketplace add /path/to/plugin-generator/dist/java-spring-ops
/plugin install java-spring-ops@java-spring-ops
```

Rules (`rules/`) need to be added by hand - the Claude Code plugin system
doesn't distribute them automatically. Copy
`dist/java-spring-ops/rules/*.md` to `~/.claude/rules/`.

## How to add a new agent / skill / command

**By hand**, writing the content yourself:

1. Open `config/plugin.yaml`, copy an existing entry in the relevant
   section (`agents`/`skills`/`commands`/`rules`/`hooks`) as a template.
2. `python3 generate.py --bump patch`
3. The new version is in `dist/java-spring-ops/`.

**By importing from another Claude Code plugin repo** (e.g. one you
cloned locally) - `generate.py import` reads a single markdown/shell file
and appends it to `config/plugin.yaml` in the right format:

```bash
# agent - id/description/tools/model are pulled from the source's frontmatter
python3 generate.py import --from ~/other-plugin/agents/some-agent.md --type agent

# skill - you can also pass just the skill's directory (it will look for SKILL.md)
python3 generate.py import --from ~/other-plugin/skills/some-skill --type skill

# command
python3 generate.py import --from ~/other-plugin/commands/some-command.md --type command

# rule - many plugins keep rules as files with no frontmatter/description,
# so --description is required here
python3 generate.py import --from ~/other-plugin/rules/common/security.md --type rule \
  --id security-baseline --description "Baseline security rules imported from another plugin"

# hook - a raw script has no event/matcher metadata, so these flags are
# required; the description is guessed from the script's first comment if possible
python3 generate.py import --from ./some-hook.sh --type hook \
  --event PreToolUse --matcher Bash
```

Useful flags: `--id` (override the detected id), `--description`
(override/fill in the description), `--dry-run` (show what would be
added, write nothing), `--force` (overwrite an existing entry with the
same id, and bypass the security-scan blocking described below, instead
of failing). Import only appends to `config/plugin.yaml` - `dist/` still
needs to be refreshed separately (`python3 generate.py --bump patch`).

## Security scan on import

Importing a hook script or a skill's resource files means pulling in code
you didn't write, from a repo you don't control. `generate.py import`
scans that content before it's copied anywhere:

- **Hook scripts** (`--type hook`) - the whole script is scanned.
- **Skill resource files** (`--type skill`) - every file found alongside
  `SKILL.md` (scripts/, references/, assets/, ...) is scanned. Files that
  can't be decoded as UTF-8 (images, other binaries) are skipped and
  reported separately as "not security-scanned" rather than silently
  ignored.

The scan is a lightweight, dependency-free set of regex heuristics (see
`generator/security_scan.py`) looking for things like: piping a download
straight into a shell (`curl ... | bash`), reverse-shell one-liners,
destructive commands (`rm -rf /`, fork bombs), privilege escalation
(`sudo`, `chmod 777`), dynamic code execution / obfuscation (`eval(`,
`base64 -d | sh`, `subprocess(..., shell=True)`), reads of credential
files (`~/.ssh/id_rsa`, `~/.aws/credentials`), and hardcoded secrets
(AWS keys, private key blocks, API tokens). It is not a substitute for a
real scanner (semgrep, gitleaks, bandit, ...) in CI - it's a fast net for
the obviously dangerous stuff.

Behavior when something is found:

- **A real import is blocked** with a report of every finding (pattern,
  file, line, and why it matters) and a non-zero exit code - nothing is
  written to `config/plugin.yaml` or `static/`.
- **`--dry-run`** never blocks (it doesn't write anything anyway) - it
  just prints the findings under a `SECURITY FINDINGS` section so you can
  see up front that a real run would be blocked.
- **`--force`** imports anyway, but the findings are still printed as a
  `WARNING` right before the `[import] OK` line, so bypassing the check
  is always visible in the output, never silent.

Separately, every resource file's path is checked to resolve *inside*
the source skill's directory. A symlink (or similar trick) pointing
outside of it is always rejected - this is a structural safety check, not
a content heuristic, so **`--force` does not bypass it**.

```bash
python3 generate.py import --from ~/other-plugin/hooks/some-hook.sh --type hook \
  --event PreToolUse --matcher Bash
# -> blocked with a SECURITY FINDINGS report if the script matches a
#    dangerous pattern; re-run with --force to import anyway
```

## Skills with extra resource files (Python scripts, references, assets, ...)

`config/plugin.yaml` only holds a skill's `description` and its `body`
(the markdown that becomes `SKILL.md`). If a skill also needs supporting
files - a Python script under `scripts/`, a reference doc under
`references/`, a template under `assets/`, whatever - those don't go in
the YAML at all. Instead:

1. Put them under `static/skills/<skill-id>/`, mirroring the layout you
   want next to the generated `SKILL.md`, e.g.:
   ```
   static/skills/database-migrations/scripts/check_pending_migrations.py
   ```
2. In the skill's `body` (in `config/plugin.yaml`), tell Claude to use it
   by its relative path, e.g. "run `scripts/check_pending_migrations.py`
   to list pending migrations."
3. `python3 generate.py` (or `--bump patch`) - every file under
   `static/skills/<skill-id>/` is copied next to `SKILL.md` in
   `dist/java-spring-ops/skills/<skill-id>/`, preserving subfolders and
   file permissions (so a script you `chmod +x`'d stays executable).

This is convention-based, not something you declare per-file in the
config - a skill with no `static/skills/<skill-id>/` directory is
completely unaffected, and the CLI output tells you which skills picked
up extra files:

```
skills:   10 (1 with extra resource files: database-migrations (1))
```

`generate.py import --type skill` picks this up too: if you point it at
a skill *directory* (not a bare `SKILL.md` file), anything else in that
directory besides `SKILL.md` is copied into `static/skills/<id>/`
automatically (`--dry-run` only previews which files would be copied,
it doesn't write them; a real import also runs the security scan
described above over those files before copying anything).

A skill (or hook) that bundles extra files isn't only flagged to whoever
runs the import - it's also called out in the generated plugin itself, so
anyone installing it sees it too: the generated `SKILL.md` gets a
"Bundled resources" note listing the files, and the generated
`README.md`/`CLAUDE.md` entry for that skill/hook is annotated the same
way, e.g. `- **database-migrations** — ... _(bundles 1 extra file(s):
scripts/check_pending_migrations.py)_`.

## Which components can carry extra resource files - and which can't

This isn't a generator choice - it follows what the Claude Code plugin
format itself supports:

- **Skills** are the one component explicitly designed to bundle files
  (scripts/references/assets) alongside their main markdown - see above.
- **Hooks** already reference an external script, and that script can in
  turn need its own support files (a shared Python module, a lookup
  table, a config file). Same convention: drop them under
  `static/hooks/<hook-id>/`, and they're copied into
  `hooks/scripts/<hook-id>/` next to the hook's own script (kept in a
  subfolder, not flat, so two hooks' resource files never collide).
  Reference them from the script relative to its own location, e.g. in
  bash: `dir=$(dirname "$0")/<hook-id>; cat "$dir/extra_patterns.txt"`.
  A hook with no such directory (the common case - one self-contained
  script) is unaffected, and `generate.py` reports it the same way:
  `hooks: 4 (1 with extra resource files: secret-scan (1))`.
- **Agents, commands and rules are single markdown files** in Claude
  Code's own plugin format - there's no bundled-resources concept for
  them at all, so there's nothing for the generator to copy. If an agent
  or command needs to run a script, that script should live in the
  project the agent is working in (and be invoked via the agent's Bash
  tool access), not be packaged with the plugin itself.

## Enabling MCP integrations (GitLab / Jira)

Disabled by default. In `config/plugin.yaml`, under `mcp_servers`, set
`enabled: true` on `gitlab` and/or `atlassian`, then run
`python3 generate.py --bump patch`. Details and ready-to-use configs
(including for the disabled integrations) are in
`dist/java-spring-ops/docs/mcp-integrations.md`.

## Structure of this repo

```
config/plugin.yaml       <- the single source of truth (the whole plugin)
generator/                <- generator code (config_model, render, build, importer, security_scan)
templates/*.j2             <- Jinja2 templates, one per component type
static/hooks/*.sh          <- ready-made hook scripts (bash + jq)
static/hooks/<hook-id>/    <- optional extra support files for a hook's script
static/skills/<skill-id>/  <- optional extra files for a skill (scripts/, references/, ...)
generate.py                 <- CLI
dist/java-spring-ops/       <- the generated plugin (ready to install)
```
