"""Gate runner: clone a PR branch and execute configured quality checks."""

from __future__ import annotations

import asyncio
import logging
import shlex
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_CLONE_TIMEOUT = 120
_COMMAND_TIMEOUT = 300


@dataclass
class GateResult:
    command: str
    exit_code: int
    output: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass
class GatesReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def summary(self) -> str:
        lines = []
        for r in self.results:
            status = "✅ PASS" if r.passed else "❌ FAIL"
            lines.append(f"{status}: `{r.command}`")
            if not r.passed and r.output.strip():
                trimmed = r.output.strip()[-2000:]  # keep tail (most relevant)
                lines.append(f"```\n{trimmed}\n```")
        return "\n".join(lines)


async def run_gates(
    repo_owner: str,
    repo_name: str,
    branch: str,
    commands: list[str],
    github_token: str,
) -> GatesReport:
    """Clone a PR branch into a temp dir and run quality gate commands.

    Args:
        repo_owner: GitHub repo owner.
        repo_name: GitHub repo name.
        branch: Branch to check out (the PR head branch).
        commands: Shell commands to run in sequence inside the repo.
        github_token: Token for cloning the repo.

    Returns:
        GatesReport with per-command results.
    """
    report = GatesReport()

    with tempfile.TemporaryDirectory(prefix="swe-gates-") as tmpdir:
        repo_dir = Path(tmpdir) / repo_name
        clone_url = f"https://x-access-token:{github_token}@github.com/{repo_owner}/{repo_name}.git"

        logger.info("Cloning %s/%s branch %s for gate checks", repo_owner, repo_name, branch)
        clone_ok = await _run_cmd(
            f"git clone --depth=1 --branch {shlex.quote(branch)} {clone_url} {repo_dir}",
            cwd=Path(tmpdir),
            timeout=_CLONE_TIMEOUT,
        )
        if not clone_ok.passed:
            logger.error("Clone failed: %s", clone_ok.output[:500])
            report.results.append(clone_ok)
            return report

        for command in commands:
            logger.info("Running gate: %s", command)
            result = await _run_cmd(command, cwd=repo_dir, timeout=_COMMAND_TIMEOUT)
            report.results.append(result)
            if not result.passed:
                logger.info("Gate failed, stopping early: %s", command)
                break  # fail-fast

    return report


async def _run_cmd(command: str, cwd: Path, timeout: int) -> GateResult:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace")
        return GateResult(command=command, exit_code=proc.returncode or 0, output=output)
    except asyncio.TimeoutError:
        proc.kill()
        return GateResult(
            command=command,
            exit_code=1,
            output=f"Command timed out after {timeout}s",
        )
