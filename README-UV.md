# Running this with uv

[uv](https://docs.astral.sh/uv/) is a fast Python package/project manager.
It can run `generate.py` without you having to create or activate a
virtualenv by hand. Two ways to do it, pick whichever you prefer.

## Install uv (if you don't have it yet)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: brew install uv   /   pipx install uv
```

## Option 1 — one-off runs, no project setup

Point `uv run` at `requirements.txt` and it builds a small cached
environment on the fly, then runs the script in it:

```bash
uv run --with-requirements requirements.txt generate.py --dry-run
uv run --with-requirements requirements.txt generate.py
uv run --with-requirements requirements.txt generate.py --bump patch
```

The import command works the same way:

```bash
uv run --with-requirements requirements.txt generate.py import \
  --from ./some-rule.md --type rule --id my-rule --description "..."
```

The first call downloads and caches PyYAML + Jinja2; every call after
that reuses the cache, so it's effectively instant. Nothing is written
outside this directory (no global installs, no `dist/` files touched
until the script itself writes them).

## Option 2 — a persistent project environment

If you'll be running this often and want a normal `.venv/` you can also
activate with other tools:

```bash
uv venv
uv pip install -r requirements.txt
uv run generate.py
uv run generate.py --bump patch
```

After the first `uv venv` + `uv pip install`, plain `uv run generate.py`
is enough for every later call - uv finds and reuses `.venv/`
automatically. Add `.venv/` to `.gitignore` if you go this route (it's
not tracked in this repo's `.gitignore` by default, since the generator
also works fine without ever creating one).

## Which one to use

Option 1 is the simplest if you only touch this generator occasionally
(e.g. once when adding a new agent/skill). Option 2 is nicer if you're
actively developing the generator itself and want a normal editor/IDE
Python environment to point at.
