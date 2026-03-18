"""Check that required environment variables are set before starting."""

import os
import sys
from pathlib import Path

# Load .env from repo root if present
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

ALWAYS_REQUIRED = [
    "ANTHROPIC_API_KEY",
    "LANGSMITH_API_KEY_PROD",
    "SANDBOX_TYPE",
]

SANDBOX_REQUIRED = {
    "local": ["LOCAL_SANDBOX_ROOT_DIR"],
    "daytona": ["DAYTONA_API_KEY"],
    "runloop": ["RUNLOOP_API_KEY"],
    "langsmith": ["LANGSMITH_API_KEY_PROD"],
}

missing = [k for k in ALWAYS_REQUIRED if not os.getenv(k)]

# GitHub auth: PAT OR GitHub App — one of the two must be present
has_pat = bool(os.getenv("GITHUB_TOKEN"))
has_app = all(os.getenv(k) for k in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_INSTALLATION_ID"))
if not has_pat and not has_app:
    missing.append("GITHUB_TOKEN (or GITHUB_APP_ID + GITHUB_APP_PRIVATE_KEY + GITHUB_APP_INSTALLATION_ID)")

sandbox_type = os.getenv("SANDBOX_TYPE", "langsmith")
missing += [k for k in SANDBOX_REQUIRED.get(sandbox_type, []) if not os.getenv(k)]

if missing:
    print("❌ Missing required environment variables:")
    for k in missing:
        print(f"   {k}")
    print("\nCopy .env.example to .env and fill in the values.")
    sys.exit(1)

if sandbox_type == "local":
    root = os.getenv("LOCAL_SANDBOX_ROOT_DIR", "")
    if not os.path.isdir(root):
        print(f"❌ LOCAL_SANDBOX_ROOT_DIR does not exist: {root!r}")
        sys.exit(1)

auth_mode = "GitHub App" if has_app else "PAT (GITHUB_TOKEN)"
print("✅ Environment looks good.")
print(f"   SANDBOX_TYPE={sandbox_type}")
print(f"   GitHub auth={auth_mode}")
if sandbox_type == "local":
    print(f"   LOCAL_SANDBOX_ROOT_DIR={os.getenv('LOCAL_SANDBOX_ROOT_DIR')}")
