"""Check that required environment variables are set before starting."""

import os
import sys

REQUIRED = [
    "ANTHROPIC_API_KEY",
    "GITHUB_APP_ID",
    "GITHUB_APP_PRIVATE_KEY",
    "GITHUB_APP_INSTALLATION_ID",
    "GITHUB_WEBHOOK_SECRET",
    "LANGSMITH_API_KEY_PROD",
    "SANDBOX_TYPE",
]

CONDITIONAL = {
    "local": ["LOCAL_SANDBOX_ROOT_DIR"],
    "modal": [],
    "daytona": ["DAYTONA_API_KEY"],
    "runloop": ["RUNLOOP_API_KEY"],
    "langsmith": ["LANGSMITH_API_KEY_PROD"],
}

missing = [k for k in REQUIRED if not os.getenv(k)]

sandbox_type = os.getenv("SANDBOX_TYPE", "langsmith")
extra_required = CONDITIONAL.get(sandbox_type, [])
missing += [k for k in extra_required if not os.getenv(k)]

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

print("✅ Environment looks good.")
print(f"   SANDBOX_TYPE={sandbox_type}")
if sandbox_type == "local":
    print(f"   LOCAL_SANDBOX_ROOT_DIR={os.getenv('LOCAL_SANDBOX_ROOT_DIR')}")
