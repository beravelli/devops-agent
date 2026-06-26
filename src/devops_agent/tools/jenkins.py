"""CI/CD triage tools for Jenkins (read-only REST API).

The "CI/CD debugging" half of the agent: did the last build pass, why did it
fail (console log + which pipeline stage), what tests failed, and is the queue
blocked. Authenticates with a Jenkins user + API token over HTTP basic auth.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..config import get_settings
from ..safety import redact
from .base import not_configured
from .obs_http import request_json


def _configured() -> bool:
    return bool(get_settings().jenkins_url)


def _auth() -> tuple[str, str] | None:
    s = get_settings()
    if s.jenkins_user and s.jenkins_token:
        return (s.jenkins_user, s.jenkins_token)
    return None


def _job_path(job: str) -> str:
    """Convert "folder/sub/name" into Jenkins' "job/folder/job/sub/job/name"."""
    segments = [seg for seg in job.strip("/").split("/") if seg and seg != "job"]
    return "/".join(f"job/{seg}" for seg in segments)


def _get(path: str, params: dict[str, Any] | None = None):
    s = get_settings()
    return request_json("GET", s.jenkins_url, path, params=params, auth=_auth(), settings=s)


def _missing() -> str:
    return not_configured("Jenkins", "DEVOPS_AGENT_JENKINS_URL")


@tool
def jenkins_job_status(job: str) -> str:
    """Show the status of a Jenkins job's most recent build.

    Use first when triaging a pipeline: tells you if the last build passed,
    failed, or is still running, plus its number, duration, and URL.

    Args:
        job: Job path, e.g. "deploy-prod" or "platform/deploy-prod" for a folder.
    """
    if not _configured():
        return _missing()
    tree = "number,result,building,timestamp,duration,url,displayName"
    res = _get(f"/{_job_path(job)}/lastBuild/api/json", {"tree": tree})
    if not res.ok:
        return f"Jenkins job status failed for {job!r}: {res.error}"
    b = res.data
    state = "BUILDING" if b.get("building") else (b.get("result") or "UNKNOWN")
    dur = b.get("duration", 0) / 1000 if b.get("duration") else 0
    return (
        f"job={job} build=#{b.get('number', '?')} result={state} "
        f"duration={dur:.0f}s\nurl={b.get('url', '')}"
    )


@tool
def jenkins_build_log(job: str, build: str = "lastBuild", tail_lines: int = 120) -> str:
    """Fetch the tail of a Jenkins build's console log.

    Use after jenkins_job_status shows a failure — the tail of the console log
    usually contains the actual error (compile error, failed step, stack trace).

    Args:
        job: Job path, e.g. "platform/deploy-prod".
        build: Build selector: a number, "lastBuild", "lastFailedBuild", etc.
        tail_lines: How many trailing lines to return.
    """
    if not _configured():
        return _missing()
    res = _get(f"/{_job_path(job)}/{build}/consoleText")
    if not res.ok:
        return f"Jenkins console log failed for {job!r} {build}: {res.error}"
    text = res.data if isinstance(res.data, str) else str(res.data)
    lines = redact(text).splitlines()
    tail = lines[-tail_lines:]
    settings = get_settings()
    body = "\n".join(tail)
    if len(body) > settings.max_output_chars:
        body = body[-settings.max_output_chars :]
    return f"console log ({job} {build}, last {len(tail)} lines):\n{body}"


@tool
def jenkins_build_stages(job: str, build: str = "lastBuild") -> str:
    """Show the pipeline stages of a build and which one failed.

    Use to pinpoint *where* a Pipeline build broke (Checkout / Build / Test /
    Deploy) before diving into the console log. Requires the Pipeline Stage View
    plugin (wfapi); falls back gracefully if unavailable.

    Args:
        job: Job path.
        build: Build selector (number or "lastBuild").
    """
    if not _configured():
        return _missing()
    res = _get(f"/{_job_path(job)}/{build}/wfapi/describe")
    if not res.ok:
        return (
            f"Jenkins stage view unavailable for {job!r} {build}: {res.error}\n"
            "(This needs the Pipeline Stage View plugin; use jenkins_build_log instead.)"
        )
    data = res.data
    stages = data.get("stages", []) if isinstance(data, dict) else []
    if not stages:
        return f"No stages reported for {job} {build} (status={data.get('status', '?')})."
    lines = []
    for st in stages:
        dur = st.get("durationMillis", 0) / 1000
        lines.append(f"- {st.get('name', '?')}: {st.get('status', '?')} ({dur:.0f}s)")
    failed = [s.get("name") for s in stages if s.get("status") in ("FAILED", "ABORTED", "UNSTABLE")]
    summary = f"\nfailed/abnormal stage(s): {', '.join(failed)}" if failed else ""
    return f"overall={data.get('status', '?')}\n" + "\n".join(lines) + summary


@tool
def jenkins_test_report(job: str, build: str = "lastBuild", max_failures: int = 25) -> str:
    """Show the test results of a build, focusing on failures.

    Use when a build is UNSTABLE or failed on tests — lists pass/fail/skip counts
    and the failing test cases with their error details.

    Args:
        job: Job path.
        build: Build selector (number or "lastBuild").
        max_failures: Max failing cases to list.
    """
    if not _configured():
        return _missing()
    res = _get(f"/{_job_path(job)}/{build}/testReport/api/json")
    if not res.ok:
        return f"Jenkins test report unavailable for {job!r} {build}: {res.error}"
    data = res.data
    fail = data.get("failCount", 0)
    passed = data.get("passCount", 0)
    skip = data.get("skipCount", 0)
    header = f"tests: {passed} passed, {fail} failed, {skip} skipped"
    if fail == 0:
        return header + " — no failures."
    failures = []
    for suite in data.get("suites", []):
        for case in suite.get("cases", []):
            if case.get("status") in ("FAILED", "REGRESSION"):
                detail = (case.get("errorDetails") or "").replace("\n", " ")[:160]
                failures.append(f"- {case.get('className', '')}.{case.get('name', '')}: {detail}")
                if len(failures) >= max_failures:
                    break
        if len(failures) >= max_failures:
            break
    return header + "\nfailing cases:\n" + redact("\n".join(failures))


@tool
def jenkins_queue() -> str:
    """Show the Jenkins build queue and why items are blocked.

    Use when builds aren't starting — the queue's "why" explains waiting on an
    executor, a lock, an upstream build, or label/agent availability.
    """
    if not _configured():
        return _missing()
    res = _get("/queue/api/json", {"tree": "items[task[name],why,stuck,buildableStartMilliseconds]"})
    if not res.ok:
        return f"Jenkins queue query failed: {res.error}"
    items = res.data.get("items", []) if isinstance(res.data, dict) else []
    if not items:
        return "Build queue is empty."
    lines = [
        f"- {i.get('task', {}).get('name', '?')}: {i.get('why', '?')}" + (" [STUCK]" if i.get("stuck") else "")
        for i in items
    ]
    return f"{len(items)} queued item(s):\n" + "\n".join(lines)


@tool
def jenkins_list_jobs(folder: str = "") -> str:
    """List Jenkins jobs and their last-build status colour.

    Use to discover job names/paths, or to scan a folder for red (failing) jobs.

    Args:
        folder: Optional folder path to list within, e.g. "platform".
    """
    if not _configured():
        return _missing()
    base = f"/{_job_path(folder)}" if folder else ""
    res = _get(f"{base}/api/json", {"tree": "jobs[name,color]"})
    if not res.ok:
        return f"Jenkins job list failed: {res.error}"
    jobs = res.data.get("jobs", []) if isinstance(res.data, dict) else []
    if not jobs:
        return "No jobs found."
    # color encodes status: blue=ok, red=failed, yellow=unstable, *_anime=building
    lines = [f"- {j.get('name', '?')} [{j.get('color', '?')}]" for j in jobs]
    return f"{len(jobs)} job(s):\n" + "\n".join(lines[:200])


JENKINS_TOOLS = [
    jenkins_job_status,
    jenkins_build_log,
    jenkins_build_stages,
    jenkins_test_report,
    jenkins_queue,
    jenkins_list_jobs,
]
