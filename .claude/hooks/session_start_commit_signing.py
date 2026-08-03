#!/usr/bin/env python3
"""SessionStart hook: stop the harness Stop hook from false-positiving on
correctly SSH-signed commits.

CC-web commits are signed with commit.gpgsign=true and gpg.format=ssh via a
host-held signer. git 2.43 short-circuits its SSH-signature verdict (%G?) to
N whenever gpg.ssh.allowedSignersFile is unset -- before it even inspects the
signature -- so the harness Stop hook's "%G? == N" presence check fires on
every locally-signed commit even though the signature is real and GitHub
reports it Verified. Pointing allowedSignersFile at ANY existing file flips
the local verdict from N to B (signature present, locally unverifiable),
which clears the false positive. Local verification can never reach G in
this container (no ssh-keygen, no access to the host signing key), so the
file is deliberately empty -- this hook does not attempt key derivation.

No-op (writes nothing) unless commit.gpgsign is true AND gpg.format is ssh,
so it is inert on surfaces that do not sign (e.g. CI runners). Idempotent:
if gpg.ssh.allowedSignersFile already names an existing file, no writes
occur. Never raises; always exits 0 -- this runs on every SessionStart and
must never wedge startup.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ALLOWED_SIGNERS_RELATIVE = Path(".config") / "git" / "ccweb_allowed_signers"

_HEADER = (
    "# Allowed-signers file for CC-web SSH-signed commits.\n"
    "# Deliberately empty: this container cannot verify signatures locally\n"
    "# (no ssh-keygen; the harness signer accepts only -Y sign), so no key\n"
    "# is listed here. Its sole purpose is to give git 2.43 a configured\n"
    "# path so it stops short-circuiting the SSH-signature verdict to N.\n"
    "# See AGENTS.md 'Commit signing'.\n"
)


def _git_config_get(key: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", key],
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return result.stdout.strip() or None


def _git_config_set_global(key: str, value: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "config", "--global", key, value],
            capture_output=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 0


def main() -> int:
    try:
        gpgsign = _git_config_get("commit.gpgsign")
        gpg_format = _git_config_get("gpg.format")
        if gpgsign != "true" or gpg_format != "ssh":
            print("[session_start_commit_signing] not an SSH-signing surface; no-op")
            return 0

        existing = _git_config_get("gpg.ssh.allowedSignersFile")
        if existing and Path(existing).is_file():
            print(f"[session_start_commit_signing] already configured: {existing}")
            return 0

        home = Path.home()
        allowed_signers_path = home / _ALLOWED_SIGNERS_RELATIVE
        allowed_signers_path.parent.mkdir(parents=True, exist_ok=True)
        if not allowed_signers_path.is_file():
            allowed_signers_path.write_text(_HEADER, encoding="utf-8")

        if _git_config_set_global("gpg.ssh.allowedSignersFile", str(allowed_signers_path)):
            print(f"[session_start_commit_signing] configured gpg.ssh.allowedSignersFile={allowed_signers_path}")
        else:
            print("[session_start_commit_signing] WARNING: failed to set gpg.ssh.allowedSignersFile (non-fatal)")
        return 0
    except Exception as exc:  # noqa: BLE001 - never wedge startup
        print(f"[session_start_commit_signing] WARNING: unexpected error, no-op ({exc})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
