"""LLM-based PR reviewer: fetch diff and get a second-model verdict."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_MAX_DIFF_BYTES = 150_000
_SYSTEM_PROMPT = """\
You are a senior software engineer performing a code review on a pull request.
Your job is to evaluate the changes and decide whether they are ready to merge.

Review for:
- Correctness: Does the code do what it claims?
- Regressions: Could this break existing behavior?
- Quality: Are there obvious bugs, security issues, or bad patterns?
- Completeness: Is anything missing that the task required?

Respond in exactly this format:
VERDICT: APPROVED
or
VERDICT: REQUEST_CHANGES

Then write a concise summary (3-10 bullet points) of your findings.
If requesting changes, be specific about what needs to be fixed.
"""


class Verdict(str, Enum):
    APPROVED = "APPROVED"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class ReviewResult:
    def __init__(self, verdict: Verdict, summary: str) -> None:
        self.verdict = verdict
        self.summary = summary

    @property
    def approved(self) -> bool:
        return self.verdict == Verdict.APPROVED

    def as_comment(self) -> str:
        icon = "✅" if self.approved else "🔄"
        label = "Approved" if self.approved else "Changes requested"
        return f"**{icon} Automated review: {label}**\n\n{self.summary}"


async def run_review(
    pr_diff: str,
    pr_title: str,
    pr_body: str,
    model_id: str,
) -> ReviewResult:
    """Run a second LLM model over the PR diff and return a verdict.

    Args:
        pr_diff: Unified diff of the PR changes.
        pr_title: PR title for context.
        pr_body: PR description for context.
        model_id: LangChain model string e.g. 'anthropic:claude-sonnet-4-6'.

    Returns:
        ReviewResult with verdict and summary.
    """
    diff_truncated = pr_diff[:_MAX_DIFF_BYTES]
    if len(pr_diff) > _MAX_DIFF_BYTES:
        diff_truncated += "\n\n[diff truncated]"

    human_content = (
        f"**PR title:** {pr_title}\n\n"
        f"**PR description:**\n{pr_body}\n\n"
        f"**Diff:**\n```diff\n{diff_truncated}\n```"
    )

    provider, _, model_name = model_id.partition(":")
    llm = init_chat_model(model_name or model_id, model_provider=provider or None)

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]

    logger.info("Running PR review with model %s", model_id)
    response = await llm.ainvoke(messages)
    raw = response.content if isinstance(response.content, str) else str(response.content)

    return _parse_response(raw)


def _parse_response(raw: str) -> ReviewResult:
    verdict = Verdict.REQUEST_CHANGES
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("VERDICT:"):
            label = stripped.removeprefix("VERDICT:").strip()
            if label == "APPROVED":
                verdict = Verdict.APPROVED
            break

    # Summary = everything after the VERDICT line
    lines = raw.splitlines()
    after_verdict = []
    found = False
    for line in lines:
        if not found and line.strip().startswith("VERDICT:"):
            found = True
            continue
        if found:
            after_verdict.append(line)

    summary = "\n".join(after_verdict).strip() or raw.strip()
    return ReviewResult(verdict=verdict, summary=summary)


async def fetch_pr_diff(
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    github_token: str,
) -> str:
    """Fetch the unified diff for a PR from GitHub."""
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pr_number}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3.diff",
            },
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text
