"""
Lightweight, dependency-free security scan for content pulled in via
`generate.py import` (hook scripts, skill resource files).

Regex heuristics, not a substitute for a real scanner (semgrep, gitleaks,
bandit, ...) in CI - the goal is to catch the obviously dangerous stuff
(droppers, reverse shells, credential exfiltration, hardcoded secrets)
before it silently becomes part of a distributed plugin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Finding:
    pattern_id: str
    message: str
    line_no: int
    line: str
    file: str = ""


def _p(pattern_id: str, regex: str, message: str) -> tuple[str, re.Pattern, str]:
    return (pattern_id, re.compile(regex, re.IGNORECASE), message)


PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # --- RCE / dropper ---------------------------------------------------
    _p("curl-pipe-shell", r"curl\s+[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b",
       "Pipes a curl download straight into a shell - runs arbitrary remote code."),
    _p("wget-pipe-shell", r"wget\s+[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b",
       "Pipes a wget download straight into a shell - runs arbitrary remote code."),
    _p("download-then-exec", r"(curl|wget)\s+[^\n]*-[oO]\s+\S+[^\n]*&&\s*chmod\s+\+x",
       "Downloads a file and immediately makes it executable - common dropper pattern."),

    # --- reverse shell / backdoor ----------------------------------------
    _p("dev-tcp-redirect", r"/dev/tcp/\S+",
       "Bash's /dev/tcp pseudo-device - typically used to open a reverse shell."),
    _p("nc-exec-shell", r"\bnc\b[^\n]*-e\s+/bin/(ba)?sh",
       "netcat with -e spawning a shell - classic reverse/bind shell."),
    _p("bash-interactive-redirect", r"bash\s+-i\s*>&",
       "Interactive bash redirected over a socket - classic reverse shell one-liner."),

    # --- destructive -------------------------------------------------------
    _p("rm-rf-root", r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(\s|$)",
       "Recursively force-deletes the filesystem root."),
    _p("rm-rf-home", r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+~(\s|/|$)",
       "Recursively force-deletes the user's home directory."),
    _p("fork-bomb", r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
       "Classic shell fork bomb - exhausts system resources."),
    _p("mkfs", r"\bmkfs\.\w+\b", "Formats a filesystem/device."),
    _p("dd-to-device", r"\bdd\s+[^\n]*of=/dev/\S+",
       "Writes raw data directly to a block device."),

    # --- privilege escalation / persistence ---------------------------------
    _p("chmod-777", r"chmod\s+(-R\s+)?0?777\b",
       "Makes files/directories world-writable and world-executable."),
    _p("persist-shell-rc", r">>\s*~?/?(\.bashrc|\.zshrc|\.profile|/etc/crontab)\b",
       "Appends to a shell startup file or crontab - persistence mechanism."),
    _p("crontab-edit", r"\bcrontab\s+-", "Modifies the user's crontab - persistence mechanism."),
    _p("sudo-usage", r"(^|[\s;&|])sudo\s+\S", "Uses sudo - escalates privileges."),

    # --- dynamic execution / obfuscation --------------------------------
    _p("py-eval", r"\beval\s*\(", "Dynamic eval() of a string - common obfuscation/injection vector."),
    _p("py-exec", r"\bexec\s*\(", "Dynamic exec() of a string - common obfuscation/injection vector."),
    _p("bash-eval-subst", r"eval\s+\"?\$\(", "Evaluates the output of a command substitution as code."),
    _p("base64-pipe-shell", r"base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh",
       "Decodes base64 and pipes it straight into a shell - hides the real payload."),
    _p("os-system", r"os\.system\s*\(", "os.system() call - shell injection risk, prefer subprocess without shell=True."),
    _p("subprocess-shell-true", r"subprocess\.\w+\([^\n]*shell\s*=\s*True",
       "subprocess call with shell=True - shell injection risk."),
    _p("py-dunder-import", r"__import__\s*\(", "Dynamic __import__() - common obfuscation vector."),

    # --- exfiltration / credential harvesting -----------------------------
    _p("ssh-key-access", r"~?/?\.ssh/(id_rsa|id_ed25519|id_ecdsa)\b",
       "References a private SSH key file."),
    _p("aws-creds-access", r"~?/?\.aws/credentials\b", "References the AWS credentials file."),
    _p("netrc-access", r"~?/?\.netrc\b", "References .netrc - often holds saved credentials."),
    _p("passwd-shadow-access", r"/etc/(passwd|shadow)\b", "References the system password/shadow file."),
    _p("curl-post-file", r"curl\s+[^\n]*(-d|--data(-binary)?)\s+@\S+",
       "Uploads a local file's contents via curl - possible exfiltration."),

    # --- hardcoded secrets (aligned with static/hooks/secret-scan.sh) ------
    _p("aws-access-key-id", r"AKIA[0-9A-Z]{16}", "Looks like an AWS access key id."),
    _p("private-key-block", r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
       "Contains a private key block."),
    _p("hardcoded-secret-literal",
       r"(api[_-]?key|secret|token)[\"']?\s*[:=]\s*[\"'][A-Za-z0-9/+_-]{20,}[\"']",
       "Looks like a hardcoded API key/secret/token literal."),
    _p("stripe-live-key", r"sk_live_[A-Za-z0-9]{16,}",
       "Looks like a live Stripe secret key."),
]


def scan_text(text: str) -> list[Finding]:
    """Runs every pattern against `text` and returns one Finding per match
    (first matching line only, per pattern - avoids flooding the report when
    the same dangerous construct repeats)."""
    findings: list[Finding] = []
    lines = text.splitlines()
    for pattern_id, regex, message in PATTERNS:
        for line_no, line in enumerate(lines, start=1):
            if regex.search(line):
                snippet = line.strip()
                if len(snippet) > 120:
                    snippet = snippet[:117] + "..."
                findings.append(Finding(pattern_id=pattern_id, message=message, line_no=line_no, line=snippet))
                break
    return findings


def format_findings(findings: list[Finding], source: str) -> str:
    lines = [f"security scan of '{source}' found {len(findings)} issue(s):"]
    for f in findings:
        where = f"{f.file}:{f.line_no}" if f.file else f"line {f.line_no}"
        lines.append(f"  - [{f.pattern_id}] {where}: {f.message}\n      {f.line}")
    return "\n".join(lines)
