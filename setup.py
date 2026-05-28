#!/usr/bin/env python3
"""Set up the Lakehouse Trading System development environment."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def check_python_version() -> None:
    if sys.version_info < (3, 12):
        print(f"[WARNING] Python 3.12+ required. Found: {sys.version}")
    else:
        print(f"Python version: {sys.version.split()[0]}")


def create_venv() -> None:
    venv_path = ROOT / ".venv"
    if not venv_path.exists():
        print("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
    else:
        print("Virtual environment already exists.")


def fix_venv_activate_for_git_bash() -> None:
    """Patch .venv/Scripts/activate to use forward slashes for Git Bash compatibility.

    Python's venv module generates activate scripts with Windows backslashes, e.g.:
        VIRTUAL_ENV="C:\\Users\\user\\repo\\.venv"

    Git Bash interprets backslash sequences (\\U, \\G, etc.) as escapes, corrupting PATH.
    This function converts to forward slashes which work on both Windows and Unix:
        VIRTUAL_ENV="/c/Users/user/repo/.venv"
    """
    activate_path = ROOT / ".venv" / "Scripts" / "activate"
    if not activate_path.exists():
        return

    content = activate_path.read_text(encoding="utf-8")

    # Check if already fixed (contains forward slashes in VIRTUAL_ENV line)
    if 'VIRTUAL_ENV="/' in content:
        print("Venv activate script already fixed for Git Bash.")
        return

    # Convert Windows paths to Git Bash format: C:\path -> /c/path
    def convert_path(match: re.Match[str]) -> str:
        path = match.group(1)
        # Convert drive letter: C:\ -> /c/
        if len(path) >= 2 and path[1] == ":":
            drive = path[0].lower()
            path = f"/{drive}{path[2:]}"
        # Convert backslashes to forward slashes
        path = path.replace("\\", "/")
        return f'VIRTUAL_ENV="{path}"'

    fixed = re.sub(r'VIRTUAL_ENV="([^"]+)"', convert_path, content)
    activate_path.write_text(fixed, encoding="utf-8")
    print("Fixed venv activate script for Git Bash compatibility.")


def get_venv_python() -> str:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    raise FileNotFoundError("Virtual environment Python not found. Run: python setup.py")


def install_dependencies() -> None:
    print("Upgrading pip...")
    venv_python = get_venv_python()
    subprocess.run([venv_python, "-m", "pip", "install", "--upgrade", "pip"], check=False)
    print("Installing dependencies...")
    subprocess.run(
        [venv_python, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")],
        check=True,
    )


def install_precommit() -> None:
    print("Installing pre-commit hooks...")
    venv_python = get_venv_python()
    subprocess.run([venv_python, "-m", "pip", "install", "pre-commit", "detect-secrets"], check=False)
    pre_commit_path = ROOT / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "pre-commit"
    subprocess.run([str(pre_commit_path), "install"], check=False, cwd=ROOT)


def check_postgres() -> None:
    if shutil.which("psql"):
        result = subprocess.run(["psql", "--version"], capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            print(f"[WARNING] psql returned exit code {result.returncode}")
        else:
            print(f"PostgreSQL is installed: {result.stdout.strip()}")
    else:
        print("[WARNING] PostgreSQL is not installed or not in PATH.")
        print("Please install PostgreSQL 16 from: https://www.postgresql.org/download/windows/")


def check_docker() -> None:
    if shutil.which("docker"):
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True, encoding="utf-8")
        print(f"Docker is installed: {result.stdout.strip()}")
    else:
        print("[WARNING] Docker is not installed or not in PATH.")
        print("Please install Docker Desktop from: https://www.docker.com/products/docker-desktop")


def check_terraform() -> None:
    if shutil.which("terraform"):
        result = subprocess.run(["terraform", "version"], capture_output=True, text=True, encoding="utf-8")
        first_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
        print(f"Terraform: {first_line}")
    else:
        print("[WARNING] Terraform is not installed.")


def configure_aws_sso() -> None:
    print()
    print("Checking AWS CLI and SSO configuration...")
    if not shutil.which("aws"):
        print("[WARNING] AWS CLI is not installed.")
        print("Install AWS CLI v2 from: https://awscli.amazonaws.com/AWSCLIV2.msi")
        return

    print("AWS CLI is installed.")
    aws_config = Path.home() / ".aws" / "config"
    try:
        aws_config_text = aws_config.read_text(encoding="utf-8") if aws_config.exists() else ""
    except (OSError, UnicodeDecodeError):
        aws_config_text = ""
    if "[profile company-aws-profile]" in aws_config_text:
        print("[INFO] AWS SSO profile 'company-aws-profile' is configured.")
    else:
        print("[INFO] AWS SSO profile 'company-aws-profile' not found.")
        print("Configure it with: aws configure sso --profile company-aws-profile")


def create_config_files() -> None:
    print("Creating configuration files...")
    if not (ROOT / "config" / "config.yaml").exists():
        shutil.copy(ROOT / "config" / "config.yaml.example", ROOT / "config" / "config.yaml")
        print("[WARNING] Please edit config/config.yaml with your settings.")
    if not (ROOT / "terraform" / "terraform.tfvars").exists():
        shutil.copy(ROOT / "terraform" / "terraform.tfvars.example", ROOT / "terraform" / "terraform.tfvars")
        print("[WARNING] Please edit terraform/terraform.tfvars with your AWS settings.")


def configure_git() -> None:
    subprocess.run(["git", "config", "push.autoSetupRemote", "true"], cwd=ROOT, check=False)
    print("Git configured: push.autoSetupRemote = true")


def check_gemini_cli() -> None:
    print()
    print("Checking Gemini CLI (gemini)...")
    if not shutil.which("gemini"):
        print("[WARNING] Gemini CLI is not installed or not in PATH.")
        print("The executor pipeline requires Gemini CLI for LLM inference (Decision 53).")
        print("Install (preview required for Gemini 3 models):")
        print("  npm install -g @google/gemini-cli@preview")
        print("Authenticate: run 'gemini' once to complete Google OAuth browser flow.")
        return

    version_result = subprocess.run(
        ["gemini", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    version_str = (version_result.stdout or version_result.stderr or "unknown").strip()
    print(f"Gemini CLI: {version_str}")

    # Warn if version appears to be stable (0.39.x) rather than preview (0.40.0+).
    # Only preview builds support Gemini 3 models.
    if version_str and not version_str.startswith("unknown"):
        import re

        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_str)
        if match:
            major, minor, _ = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if major == 0 and minor < 40:
                print("[WARNING] Gemini CLI version appears to be stable (0.39.x).")
                print("Preview (0.40.0+) is required for Gemini 3 models (gemini-3-pro-preview, gemini-3-flash-preview).")
                print("Upgrade: npm install -g @google/gemini-cli@preview")
            else:
                print("[INFO] Gemini CLI version supports Gemini 3 models.")


def check_gh_cli() -> None:
    print()
    print("Checking GitHub CLI (gh)...")
    if not shutil.which("gh"):
        print("[WARNING] gh CLI is not installed or not in PATH.")
        print("CI feedback loop and automated PR creation will fall back to manual operation.")
        print("Install: winget install GitHub.cli")
        print("Authenticate: gh auth login (select GitHub.com, HTTPS, browser auth)")
        return

    result = subprocess.run(["gh", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    first_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
    print(f"gh CLI: {first_line}")

    auth_result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if auth_result.returncode == 0:
        print("[INFO] gh auth: authenticated.")
    else:
        print("[ERROR] gh CLI is not authenticated. CI feedback loop and PR creation will fail.")
        print("Run: gh auth login (select GitHub.com, HTTPS, browser auth)")


def check_git_bash() -> None:
    print()
    print("Checking Git Bash...")
    git_bash_path = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash_path.exists():
        print(f"Git Bash found: {git_bash_path}")
    else:
        print("[WARNING] Git Bash not found at expected path: C:\\Program Files\\Git\\bin\\bash.exe")
        print("Install Git for Windows from: https://git-scm.com/download/win")
        print("Git Bash is required for agent workflow scripts.")


def main() -> None:
    print("Setting up Lakehouse Trading System...")
    print()

    check_python_version()
    create_venv()
    fix_venv_activate_for_git_bash()
    install_dependencies()
    install_precommit()

    print()
    print("Checking PostgreSQL installation...")
    check_postgres()

    create_config_files()
    check_docker()
    check_terraform()
    configure_aws_sso()
    configure_git()
    check_gh_cli()
    check_gemini_cli()
    check_git_bash()

    print()
    print("Setup complete!")
    print()
    print("Next steps:")
    print("  1. Edit configuration files in config/ (config.yaml)")
    print("  2. Ensure PostgreSQL is running")
    print("  3. Create the trading database: createdb -U postgres trading")
    print("  4. Run tests: pytest tests/")
    print("  5. Run the app locally: python -m src.main live")


if __name__ == "__main__":
    main()
