"""Post-PR review pipeline: gates + LLM review + agent feedback loop."""

from __future__ import annotations

import logging
from typing import Any

from langgraph_sdk import get_client

from .gates import run_gates
from .review import ReviewResult, Verdict, fetch_pr_diff, run_review
from .utils.github_comments import post_github_comment
from .utils.swe_config import load_swe_config

logger = logging.getLogger(__name__)

_RETRY_METADATA_KEY = "swe_review_retries"
_AGENT_BRANCH_PREFIX = "open-swe/"


def is_agent_branch(branch: str) -> bool:
    return branch.startswith(_AGENT_BRANCH_PREFIX)


def thread_id_from_branch(branch: str) -> str | None:
    """Extract the LangGraph thread_id from an open-swe branch name."""
    if not branch.startswith(_AGENT_BRANCH_PREFIX):
        return None
    return branch.removeprefix(_AGENT_BRANCH_PREFIX)


async def run_review_pipeline(
    *,
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    pr_title: str,
    pr_body: str,
    branch: str,
    github_token: str,
    langgraph_url: str,
) -> None:
    """Run gates + LLM review on an agent-opened PR and reconcile failures.

    - Runs configured quality gates against the PR branch.
    - If gates pass, runs a second-model LLM code review.
    - On failure: posts a comment and queues feedback to the agent thread.
    - On approval: posts an approval comment.
    - Respects max_retries from swe_config.json.
    """
    thread_id = thread_id_from_branch(branch)
    if not thread_id:
        logger.warning("Could not extract thread_id from branch %s", branch)
        return

    config = load_swe_config()
    repo_config = {"owner": repo_owner, "name": repo_name}

    retry_count = await _get_retry_count(thread_id, langgraph_url)
    max_retries = config["review"]["max_retries"]

    if retry_count >= max_retries:
        logger.info(
            "PR #%d has hit max_retries (%d) for thread %s — no more automated review",
            pr_number,
            max_retries,
            thread_id,
        )
        await post_github_comment(
            repo_config,
            pr_number,
            f"⚠️ Automated review stopped after {max_retries} retries. Please review manually.",
            token=github_token,
        )
        return

    feedback_lines: list[str] = []

    # --- Gates ---
    if config["gates"]["enabled"] and config["gates"]["commands"]:
        logger.info("Running gates for PR #%d branch %s", pr_number, branch)
        gates_report = await run_gates(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            commands=config["gates"]["commands"],
            github_token=github_token,
        )
        gate_comment = f"**🔍 Gate results (attempt {retry_count + 1}/{max_retries}):**\n\n{gates_report.summary()}"
        await post_github_comment(repo_config, pr_number, gate_comment, token=github_token)

        if not gates_report.passed:
            feedback_lines.append("## Gate failures\n\nThe following quality gates failed on your PR branch:\n")
            feedback_lines.append(gates_report.summary())
            feedback_lines.append("\nPlease fix these issues and push an updated commit.")
            await _queue_feedback(thread_id, "\n".join(feedback_lines), langgraph_url)
            await _increment_retry_count(thread_id, retry_count, langgraph_url)
            return

    # --- LLM review ---
    if config["review"]["enabled"]:
        logger.info("Running LLM review for PR #%d with model %s", pr_number, config["review"]["model"])
        pr_diff = await fetch_pr_diff(repo_owner, repo_name, pr_number, github_token)
        review_result = await run_review(
            pr_diff=pr_diff,
            pr_title=pr_title,
            pr_body=pr_body,
            model_id=config["review"]["model"],
        )
        await post_github_comment(repo_config, pr_number, review_result.as_comment(), token=github_token)

        if not review_result.approved:
            feedback_lines.append("## Code review feedback\n\nThe automated reviewer requested changes on your PR:\n")
            feedback_lines.append(review_result.summary)
            feedback_lines.append("\nPlease address these comments and push an updated commit.")
            await _queue_feedback(thread_id, "\n".join(feedback_lines), langgraph_url)
            await _increment_retry_count(thread_id, retry_count, langgraph_url)
            return

    # --- All checks passed ---
    logger.info("PR #%d passed all checks (thread %s)", pr_number, thread_id)
    await post_github_comment(
        repo_config,
        pr_number,
        "✅ All automated checks passed. Ready for merge.",
        token=github_token,
    )


async def _queue_feedback(thread_id: str, feedback: str, langgraph_url: str) -> None:
    """Queue feedback back to the agent thread to trigger a fix attempt."""
    from .webapp import queue_message_for_thread  # avoid circular import at module level

    logger.info("Queuing review feedback to thread %s", thread_id)
    await queue_message_for_thread(thread_id, feedback)


async def _get_retry_count(thread_id: str, langgraph_url: str) -> int:
    langgraph_client = get_client(url=langgraph_url)
    try:
        thread = await langgraph_client.threads.get(thread_id)
        return int(thread.get("metadata", {}).get(_RETRY_METADATA_KEY, 0))
    except Exception:
        logger.debug("Could not fetch thread %s metadata, assuming 0 retries", thread_id)
        return 0


async def _increment_retry_count(thread_id: str, current: int, langgraph_url: str) -> None:
    langgraph_client = get_client(url=langgraph_url)
    try:
        await langgraph_client.threads.update(
            thread_id,
            metadata={_RETRY_METADATA_KEY: current + 1},
        )
    except Exception:
        logger.warning("Failed to update retry count for thread %s", thread_id)
