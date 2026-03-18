"""Poll GitHub for agent-opened PRs and run the review pipeline.

Use this instead of webhooks for local development.
Runs alongside `langgraph dev` — no public URL or tunnel required.

Usage:
    python scripts/poll_prs.py --repo owner/name [--interval 30] [--langgraph-url http://localhost:2024]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_AGENT_BRANCH_PREFIX = "open-swe/"
_STATE_FILE = Path(".swe_poll_state.json")


def _load_state() -> set[int]:
    if _STATE_FILE.exists():
        return set(json.loads(_STATE_FILE.read_text()).get("processed", []))
    return set()


def _save_state(processed: set[int]) -> None:
    _STATE_FILE.write_text(json.dumps({"processed": sorted(processed)}))


async def _fetch_agent_prs(owner: str, repo: str, token: str) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            params={"state": "open", "per_page": 50},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        prs = resp.json()
    return [pr for pr in prs if pr["head"]["ref"].startswith(_AGENT_BRANCH_PREFIX)]


async def poll_once(owner: str, repo: str, token: str, langgraph_url: str, processed: set[int]) -> set[int]:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.reconcile import run_review_pipeline

    prs = await _fetch_agent_prs(owner, repo, token)
    new_prs = [pr for pr in prs if pr["number"] not in processed]

    if not new_prs:
        logger.debug("No new agent PRs found")
        return processed

    for pr in new_prs:
        pr_number = pr["number"]
        branch = pr["head"]["ref"]
        logger.info("Found new agent PR #%d: %s", pr_number, pr["title"])
        try:
            await run_review_pipeline(
                repo_owner=owner,
                repo_name=repo,
                pr_number=pr_number,
                pr_title=pr["title"],
                pr_body=pr.get("body") or "",
                branch=branch,
                github_token=token,
                langgraph_url=langgraph_url,
            )
            processed.add(pr_number)
            _save_state(processed)
            logger.info("Review pipeline completed for PR #%d", pr_number)
        except Exception:
            logger.exception("Review pipeline failed for PR #%d", pr_number)

    return processed


async def run_poller(owner: str, repo: str, token: str, langgraph_url: str, interval: int) -> None:
    processed = _load_state()
    logger.info("Polling %s/%s for agent PRs every %ds (processed so far: %d)", owner, repo, interval, len(processed))

    while True:
        try:
            processed = await poll_once(owner, repo, token, langgraph_url, processed)
        except Exception:
            logger.exception("Poll cycle failed")
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll GitHub for agent-opened PRs and run review pipeline")
    parser.add_argument("--repo", required=True, help="owner/repo to watch (e.g. asears-synmax/henry_hub)")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")
    parser.add_argument("--langgraph-url", default=os.getenv("LANGGRAPH_URL", "http://localhost:2024"))
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_APP_TOKEN")
    if not token:
        # Try gh CLI
        import subprocess
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        token = result.stdout.strip()

    if not token:
        parser.error("No GitHub token found. Set GITHUB_TOKEN or run `gh auth login`.")

    owner, _, repo = args.repo.partition("/")
    if not repo:
        parser.error("--repo must be in owner/repo format")

    asyncio.run(run_poller(owner, repo, token, args.langgraph_url, args.interval))


if __name__ == "__main__":
    main()
