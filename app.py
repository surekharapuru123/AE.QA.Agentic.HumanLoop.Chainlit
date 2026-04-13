"""Chainlit chat: repo **skills** (``.github/skills`` + ``.github/rules``) in the system prompt, **MCP** for tools.

OpenAI plans steps from skill + rule text; MCP ``call_tool`` performs external actions. The synthetic tool
``chainlit_ask_user`` uses Chainlit ``AskUserMessage`` for human-in-the-loop prompts. The Chat Completions
``tools`` / ``tool_calls`` fields mirror MCP operations plus that optional tool.

See https://docs.chainlit.io/advanced-features/mcp
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import ssl
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

# MCP stdio uses paths relative to the *subprocess* cwd. The MCP SDK defaults cwd=None and a
# stripped env — on Windows that often breaks node/npx. Pin cwd + optional full env before chainlit.
_PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(_PROJECT_ROOT)
os.environ.setdefault("CHAINLIT_APP_ROOT", str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")


def _env_truthy(key: str, default: bool = False) -> bool:
    """Whether an env var is set to a truthy string (used before full module body loads)."""
    v = os.getenv(key)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _parse_github_remote_url(url: str) -> tuple[str, str] | None:
    """Return (owner, repo_slug) from a common GitHub remote URL, or None.

    Repo slugs may contain dots (e.g. ``AE.QA.Agentic.HumanLoop.Chainlit``); patterns must not
    treat the first ``.`` as the end of the name (that incorrectly yielded ``AE``).
    """
    u = (url or "").strip()
    if not u:
        return None
    m = re.match(r"https?://github\.com/([^/]+)/([^/?#]+)", u)
    if m:
        repo = m.group(2).removesuffix(".git").strip().rstrip("/")
        if repo:
            return m.group(1), repo
    m = re.match(r"git@github\.com:([^/]+)/(.+)", u)
    if m:
        repo = m.group(2).removesuffix(".git").strip()
        if repo:
            return m.group(1), repo
    return None


def _github_owner_repo_from_git_origin() -> tuple[str, str] | None:
    """Resolve owner/repo from ``git remote get-url origin`` in this app repo."""
    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    return _parse_github_remote_url(r.stdout.strip())


def _github_owner_repo_from_env_vars() -> tuple[str | None, str | None]:
    """Parse owner/repo from ``GITHUB_REPOSITORY`` / ``ORCHESTRATOR_GITHUB_REPO`` or split env vars."""
    gh_full = (os.getenv("GITHUB_REPOSITORY") or os.getenv("ORCHESTRATOR_GITHUB_REPO") or "").strip()
    if gh_full and "/" in gh_full:
        o, _, r = gh_full.partition("/")
        o, r = o.strip(), r.strip()
        if o and r:
            return o, r
    gh_owner = (os.getenv("GITHUB_REPO_OWNER") or os.getenv("GITHUB_DEFAULT_OWNER") or "").strip()
    gh_repo = (os.getenv("GITHUB_REPO_NAME") or os.getenv("GITHUB_DEFAULT_REPO") or "").strip()
    if gh_owner and gh_repo:
        return gh_owner, gh_repo
    return None, None


def _resolved_github_owner_repo() -> tuple[str | None, str | None]:
    """GitHub owner and repo for MCP / ``pr_url`` / pins.

    By default (**git wins**): if ``git remote origin`` parses, use it so a wrong or truncated
    ``GITHUB_REPOSITORY`` in ``.env`` (e.g. ``owner/AE``) does not override the real checkout.

    Set ``CHAINLIT_GITHUB_REPOSITORY_TRUST_ENV=1`` to prefer ``.env`` when you intentionally target
    a different repo than ``origin`` (no git metadata, or fork workflow).
    """
    git_pair = _github_owner_repo_from_git_origin()
    trust_env = _env_truthy("CHAINLIT_GITHUB_REPOSITORY_TRUST_ENV", default=False)
    env_pair = _github_owner_repo_from_env_vars()

    if trust_env:
        if env_pair[0] and env_pair[1]:
            return env_pair
        if git_pair:
            return git_pair[0], git_pair[1]
        return None, None

    if git_pair:
        return git_pair[0], git_pair[1]
    if env_pair[0] and env_pair[1]:
        return env_pair
    return None, None


def _apply_github_repository_default_from_git() -> None:
    """Seed ``GITHUB_REPOSITORY`` from ``origin`` when unset; fix wrong ``GITHUB_REPOSITORY`` vs ``origin``."""
    has_full = bool((os.getenv("GITHUB_REPOSITORY") or os.getenv("ORCHESTRATOR_GITHUB_REPO") or "").strip())
    has_split = bool(
        (os.getenv("GITHUB_REPO_OWNER") or os.getenv("GITHUB_DEFAULT_OWNER") or "").strip()
    ) and bool((os.getenv("GITHUB_REPO_NAME") or os.getenv("GITHUB_DEFAULT_REPO") or "").strip())

    if not has_full and not has_split:
        got = _github_owner_repo_from_git_origin()
        if got:
            os.environ.setdefault("GITHUB_REPOSITORY", f"{got[0]}/{got[1]}")

    if has_full or (os.getenv("GITHUB_REPOSITORY") or "").strip():
        _sync_github_repository_env_with_origin()


def _sync_github_repository_env_with_origin() -> None:
    """Align ``GITHUB_REPOSITORY`` with ``git remote origin`` when they disagree (unless trust-env)."""
    if _env_truthy("CHAINLIT_GITHUB_REPOSITORY_TRUST_ENV", default=False):
        return
    gp = _github_owner_repo_from_git_origin()
    if not gp:
        return
    canon = f"{gp[0]}/{gp[1]}"
    cur = (os.getenv("GITHUB_REPOSITORY") or "").strip()
    if not cur or "/" not in cur:
        os.environ["GITHUB_REPOSITORY"] = canon
        return
    o, _, r = cur.partition("/")
    if o.strip().lower() == gp[0].lower() and r.strip().lower() == gp[1].lower():
        return
    os.environ["GITHUB_REPOSITORY"] = canon


_apply_github_repository_default_from_git()

# GitHub MCP tools where we must NOT rewrite ``owner``/``repo`` (search, fork source, profile).
_GITHUB_SKIP_WORKSPACE_OWNER_REPO_PIN = frozenset(
    {
        "fork_repository",
        "get_me",
        "search_repositories",
        "search_code",
        "search_issues",
        "search_pull_requests",
        "search_users",
    }
)


def _message_triggers_github_repo_local(user_text: str) -> bool:
    """Slash commands (or a plain “fetch repo details” line) — no OpenAI / GitHub API."""
    for line in user_text.splitlines():
        t = line.strip().lower()
        if t in ("/github-repo", "/current-repo", "/workspace-repo"):
            return True
        if t in (
            "fetch current github repo details",
            "fetch current git repo details",
        ):
            return True
    return False


def _message_triggers_git_branches_local(user_text: str) -> bool:
    for line in user_text.splitlines():
        t = line.strip().lower()
        if t in ("/git-branches", "/branches", "/list-branches"):
            return True
    return False


def _message_triggers_github_mcp_chainlit_instructions(user_text: str) -> bool:
    for line in user_text.splitlines():
        t = line.strip().lower()
        if t in ("/github-mcp", "/github-mcp-connect", "/github-mcp-setup"):
            return True
    return False


def _github_mcp_chainlit_integration_markdown() -> str:
    """How to add GitHub MCP in Chainlit to mirror Cursor ``mcp.json`` (Copilot MCP URL + Authorization)."""
    url = (os.getenv("GITHUB_MCP_URL") or "https://api.githubcopilot.com/mcp/").strip()
    auth_hint = (os.getenv("GITHUB_MCP_AUTHORIZATION") or "").strip()
    return (
        "### GitHub MCP in Chainlit (match Cursor `mcp.json`)\n\n"
        "Use this when your **Cursor** config uses a **remote** GitHub MCP, for example:\n\n"
        "```json\n"
        '"github": {\n'
        '  "url": "https://api.githubcopilot.com/mcp/",\n'
        '  "headers": { "Authorization": "<YOUR_TOKEN>" }\n'
        "}\n"
        "```\n\n"
        "#### Option A — Remote HTTP in Chainlit UI\n\n"
        "1. Open the **plug (MCP)** menu → **Add** / **Edit** a connection.\n"
        "2. Choose **Streamable HTTP** or **HTTP** (remote MCP), per your Chainlit version — "
        "**not** stdio, for this URL.\n"
        f"3. **URL:** `{url}`\n"
        "4. **Headers:** add **`Authorization`** with the **same value** you use in Cursor "
        "(often a GitHub PAT as `ghp_…`, or `Bearer ghp_…` if the UI expects a scheme — match what works in Cursor).\n"
        "5. Save, restart Chainlit if tools do not appear, then run **`/mcp-setup`** and confirm GitHub **`get_me`**.\n\n"
        "#### Option B — Stdio bridge (same pattern as Atlassian)\n\n"
        "1. Set **`GITHUB_MCP_URL`** (optional), **`GITHUB_MCP_AUTHORIZATION`** or **`GITHUB_TOKEN`** / **`GH_TOKEN`** in `.env`.\n"
        "2. In MCP settings, use command: **`node chainlit-github-mcp.cjs`** (or `npm run mcp:github` from this repo; run **`npm install`** first so `mcp-remote` is present).\n"
        "3. Run **`/mcp-setup`** and confirm GitHub tools (e.g. **`get_me`**).\n"
        "If the bridge fails on OAuth against Copilot, use **Option A** (remote HTTP in the Chainlit UI) with the same URL and header.\n\n"
        "#### Environment\n\n"
        "For Option A, the vars below are mainly for this help text; you still paste the header in the UI. "
        "For Option B, they are **required** for the bridge (same as `chainlit-atlassian-mcp.cjs` + Jira vars):\n\n"
        f"- `GITHUB_MCP_URL` — default in this message: `{url}`\n"
        + (
            "- `GITHUB_MCP_AUTHORIZATION` — **set in `.env` only on your machine**; never commit. "
            f"Currently **set** (value hidden) — paste the same string into the MCP **Authorization** header.\n"
            if auth_hint
            else "- `GITHUB_MCP_AUTHORIZATION` — optional; if unset, paste your PAT into the MCP header manually.\n"
        )
        + "\n"
        "#### Repo access for `create_branch` / REST tools\n\n"
        "Also set **`GITHUB_TOKEN`** (or **`GH_TOKEN`**) with **`repo`** scope and **`CHAINLIT_MCP_FULL_ENV=1`** "
        "if you use the **stdio** GitHub server (`@modelcontextprotocol/server-github`) instead — "
        "the Copilot-hosted URL may use different auth; use whichever matches your working Cursor setup.\n\n"
        "**Security:** If a PAT was ever pasted into chat or committed, **revoke it** on GitHub and create a new one.\n\n"
        "Other shortcuts: **`/github-repo`** (workspace slug), **`/git-branches`** (local git)."
    )


def _git_branches_local_report() -> str:
    """Local ``git`` output — no GitHub token; complements MCP ``list_branches``."""
    parts: list[str] = ["### Branches (local `git`, no GitHub API)\n"]
    try:
        r = subprocess.run(
            ["git", "branch", "-a"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        body = ((r.stdout or r.stderr) or "").strip()
        parts.append(f"```\n{body or '(empty)'}\n```\n")
    except OSError as e:
        parts.append(f"Could not run `git branch -a`: {e}\n")
    try:
        r2 = subprocess.run(
            ["git", "remote", "show", "origin"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        for line in (r2.stdout or "").splitlines():
            if "HEAD branch" in line:
                parts.append(f"\n- **{line.strip()}**")
                break
    except OSError:
        pass
    parts.extend(
        [
            "\n\n**Remote branch list via API:** use GitHub MCP **`list_branches`** — not **`get_file_contents`** on `.git/HEAD` (invalid for the API).",
            "\n\n**404 on `create_branch` / repo APIs** with the correct owner/repo usually means **the token cannot access that repository** "
            "(fine-grained token missing this repo, classic PAT without **repo**, wrong GitHub user, or **SSO** not authorized). "
            "Fix PAT + **`CHAINLIT_MCP_FULL_ENV=1`**, restart Chainlit, then **`/mcp-setup`**.",
        ]
    )
    return "".join(parts)


def _github_repo_local_report() -> str:
    """Markdown: owner/repo from env + git, clone URL, and GitHub token hint for MCP."""
    go, gr = _resolved_github_owner_repo()
    raw_remote = ""
    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            raw_remote = (r.stdout or "").strip()
    except OSError:
        pass
    env_full = (os.getenv("GITHUB_REPOSITORY") or os.getenv("ORCHESTRATOR_GITHUB_REPO") or "").strip()
    parts: list[str] = [
        "### GitHub repository (this Chainlit workspace)",
        "",
    ]
    if go and gr:
        parts.extend(
            [
                f"- **Owner:** `{go}`",
                f"- **Repo:** `{gr}`",
                f"- **Full name:** `{go}/{gr}`",
                f"- **Web:** https://github.com/{go}/{gr}",
            ]
        )
    else:
        parts.append(
            "- **Could not resolve** owner/repo — use a git checkout with **`origin`**, or set **`GITHUB_REPOSITORY`** in `.env`."
        )
    if raw_remote:
        parts.append(f"- **`git remote get-url origin`:** `{raw_remote}`")
    if env_full:
        parts.append(f"- **`GITHUB_REPOSITORY` / `ORCHESTRATOR_GITHUB_REPO` (after startup sync):** `{env_full}`")
    parts.append(
        "- **Resolution rule:** Owner/repo above follows **`git remote origin`** when this folder is a clone "
        "(so a typo like `owner/AE` in `.env` is corrected). Set **`CHAINLIT_GITHUB_REPOSITORY_TRUST_ENV=1`** to prefer `.env` over `origin`."
    )
    tok = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    parts.extend(
        [
            "",
            "**GitHub MCP authentication:** Issue/PR/file APIs need a PAT. Set **`GITHUB_TOKEN`** (or **`GH_TOKEN`**) in `.env` "
            "with **`repo`** scope, and **`CHAINLIT_MCP_FULL_ENV=1`** so the GitHub MCP child process inherits it, then restart Chainlit.",
        ]
    )
    if not tok:
        parts.append(
            "- **Token in this process:** not set — expect **`Requires authentication`** from GitHub MCP on create/update calls."
        )
    else:
        parts.append(
            "- **Token in this process:** present (value not shown). If MCP still errors, restart Chainlit after editing `.env`."
        )
    parts.extend(
        [
            "",
            "**If GitHub MCP returns 404** with the owner/repo above, the PAT often **cannot access this repo** "
            "(token is for another user, missing **`repo`** scope, or **org SSO** not authorized). Confirm with **`/mcp-setup`** → **`get_me`**.",
            "",
            "Probe the live MCP connection with **`/mcp-setup`** (GitHub **`get_me`**). Local branch tips: **`/git-branches`**.",
        ]
    )
    return "\n".join(parts)


def _pin_github_mcp_owner_repo(mcp_conn: str, real_name: str, args: dict) -> dict:
    """Force ``owner``/``repo`` to match :func:`_resolved_github_owner_repo` for repo-scoped GitHub tools.

    Applies to any tool call that includes both ``owner`` and ``repo`` (e.g. ``get_file_contents``), so the model
    cannot use truncated or example slugs like ``AE``. Skipped for search/fork/profile tools — set
    ``CHAINLIT_GITHUB_PIN_WORKSPACE_REPO=0`` to talk to arbitrary repositories on purpose.
    """
    if not _env_truthy("CHAINLIT_GITHUB_PIN_WORKSPACE_REPO", default=True):
        return args
    if "github" not in (mcp_conn or "").lower():
        return args
    if real_name in _GITHUB_SKIP_WORKSPACE_OWNER_REPO_PIN:
        return args
    wo, wr = _resolved_github_owner_repo()
    if not wo or not wr:
        return args
    if "owner" not in args or "repo" not in args:
        return args
    if str(args.get("owner", "")).strip() == wo and str(args.get("repo", "")).strip() == wr:
        return args
    return {**args, "owner": wo, "repo": wr}


def _prepare_github_mcp_tool_args(mcp_conn: str, real_name: str, args: dict) -> dict:
    """Pin ``owner``/``repo``, then apply defaults some GitHub tools expect (e.g. source ref for new branches)."""
    out = _pin_github_mcp_owner_repo(mcp_conn, real_name, args)
    if "github" not in (mcp_conn or "").lower() or not isinstance(out, dict):
        return out
    if real_name == "create_branch" and not str(out.get("from_branch") or "").strip():
        dfb = (os.getenv("GITHUB_DEFAULT_BRANCH") or "main").strip() or "main"
        out = {**out, "from_branch": dfb}
    return out


def _patch_mcp_stdio_for_chainlit() -> None:
    """Set default stdio MCP subprocess cwd to this repo; optionally inherit full os.environ.

    We patch ``StdioServerParameters`` (not ``stdio_client``) so we do not add an extra
    async context layer around the MCP client's internal ``TaskGroup`` (which can surface as
    "unhandled errors in a TaskGroup").
    """
    from pydantic import model_validator

    import mcp.client.stdio as mcp_stdio

    _orig_params = mcp_stdio.StdioServerParameters
    _orig_env = mcp_stdio.get_default_environment
    _root_str = str(_PROJECT_ROOT)

    class StdioServerParametersWithDefaultCwd(_orig_params):
        @model_validator(mode="after")
        def _default_cwd(self):
            if self.cwd is None or str(self.cwd).strip() == "":
                self.cwd = _root_str
            return self

    mcp_stdio.StdioServerParameters = StdioServerParametersWithDefaultCwd  # type: ignore[misc, assignment]

    def _get_env() -> dict[str, str]:
        if os.getenv("CHAINLIT_MCP_FULL_ENV", "").lower() in ("1", "true", "yes"):
            # Subprocess env must be str -> str
            return {k: v for k, v in os.environ.items() if isinstance(v, str)}
        return _orig_env()

    mcp_stdio.get_default_environment = _get_env


_patch_mcp_stdio_for_chainlit()

import chainlit as cl
from chainlit.chat_context import chat_context
from chainlit.context import context
from chainlit.input_widget import Select
from chainlit.session import WebsocketSession
from chainlit.user_session import user_session
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent
import httpx
from openai import AsyncOpenAI

# --- MCP + LLM chat ---

# Official @qase/mcp-server tool names (used when the Chainlit connection id does not contain "qase").
_QASE_MCP_TOOL_NAMES = frozenset(
    {
        "attach_external_issue",
        "bulk_create_cases",
        "complete_run",
        "create_case",
        "create_configuration_group",
        "create_custom_field",
        "create_defect",
        "create_environment",
        "create_milestone",
        "create_plan",
        "create_project",
        "create_result",
        "create_results_bulk",
        "create_run",
        "create_shared_parameter",
        "create_shared_step",
        "create_suite",
        "delete_attachment",
        "delete_case",
        "delete_configuration_group",
        "delete_custom_field",
        "delete_defect",
        "delete_environment",
        "delete_milestone",
        "delete_plan",
        "delete_project",
        "delete_result",
        "delete_run",
        "delete_run_public_link",
        "delete_shared_parameter",
        "delete_shared_step",
        "delete_suite",
        "detach_external_issue",
        "get_attachment",
        "get_author",
        "get_case",
        "get_custom_field",
        "get_defect",
        "get_environment",
        "get_milestone",
        "get_plan",
        "get_project",
        "get_result",
        "get_run",
        "get_run_public_link",
        "get_shared_parameter",
        "get_shared_step",
        "get_suite",
        "get_user",
        "grant_project_access",
        "list_attachments",
        "list_authors",
        "list_cases",
        "list_configurations",
        "list_custom_fields",
        "list_defects",
        "list_environments",
        "list_milestones",
        "list_plans",
        "list_projects",
        "list_results",
        "list_runs",
        "list_shared_parameters",
        "list_shared_steps",
        "list_suites",
        "list_system_fields",
        "list_users",
        "qql_help",
        "qql_search",
        "resolve_defect",
        "revoke_project_access",
        "update_case",
        "update_custom_field",
        "update_defect",
        "update_defect_status",
        "update_environment",
        "update_milestone",
        "update_plan",
        "update_result",
        "update_shared_parameter",
        "update_shared_step",
        "update_suite",
        "upload_attachment",
    }
)


def _is_qase_mcp_operation(operation: str) -> bool:
    return operation in _QASE_MCP_TOOL_NAMES


def _resolve_httpx_verify() -> bool | str | ssl.SSLContext:
    """TLS verify setting for httpx: off, PEM file, truststore (Windows/macOS cert store), or default CAs."""
    insecure = os.getenv("CHAINLIT_OPENAI_VERIFY_SSL", "1").lower() in ("0", "false", "no")
    if insecure:
        return False

    ca_path = (
        os.getenv("CHAINLIT_SSL_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
        or ""
    ).strip()
    if ca_path and Path(ca_path).is_file():
        return ca_path

    # Use OS trust store (helps corporate SSL inspection when IT deploys certs to the OS).
    ts_default = "1" if os.name == "nt" else "0"
    if os.getenv("CHAINLIT_USE_TRUSTSTORE", ts_default).lower() in ("1", "true", "yes"):
        try:
            import truststore

            return truststore.ssl_context()
        except ImportError:
            pass
    return True


def _create_openai_client(openai_timeout: float) -> AsyncOpenAI:
    """httpx client with TLS options for corporate proxies (MITM) that break default CA trust."""
    api_key = os.getenv("OPENAI_API_KEY") or ""
    base_url = (os.getenv("CHAINLIT_OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "").strip() or None

    connect_timeout = min(45.0, max(10.0, openai_timeout / 4))
    timeout = httpx.Timeout(openai_timeout, connect=connect_timeout)

    verify = _resolve_httpx_verify()
    http_client = httpx.AsyncClient(timeout=timeout, verify=verify, trust_env=True)
    return AsyncOpenAI(api_key=api_key, http_client=http_client, base_url=base_url)


def _format_connect_exception(exc: BaseException) -> str:
    parts = [f"{type(exc).__name__}: {exc!s}"]
    cur: BaseException | None = exc
    seen = 0
    while cur.__cause__ is not None and seen < 5:
        cur = cur.__cause__
        seen += 1
        parts.append(f"Caused by: {type(cur).__name__}: {cur!s}")
    return "\n".join(parts)


# --- Repo skills + rules (injected into OpenAI system prompt; MCP still executes via call_tool) ---

_CHAINLIT_SKILL_ADAPTATION = """
## Chainlit execution (this application)

You run as a **single** assistant in Chainlit. There are no Cursor subagents or `Task` launches.
- Follow the **workflow skills** below when the user asks for QA pipeline work or a specific stage.
- **All external actions** use **MCP only**: operations appear as OpenAI function names; each invocation runs
  `call_tool` on the user’s connected MCP servers. Connection names may differ from `user-atlassian` / `user-qase`
  in the docs — use the **live** tool names and parameter schemas from this session.
- Where skills mention reading tool JSON from `mcps/.../tools/` on disk, **ignore that**; schemas come from MCP here.
- When a skill asks for structured JSON handoff, match the output format in `.github/agents/*.agent.md` when applicable.
- **Do not repeat the same read** (e.g. `getJiraIssue` for the same key) unless you need fresher data: reuse JSON already in this thread’s tool messages. Repetition wastes rounds and context. For **writes** (`addComment`, etc.), only call when the skill step truly needs a new side effect.
""".strip()


def _resolve_repo_path(rel: str) -> Path:
    p = Path(rel.strip())
    return p if p.is_absolute() else (_PROJECT_ROOT / p).resolve()


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _read_skill_file(path: Path, max_chars: int) -> str:
    if not path.is_file():
        return f"[Missing skill file: `{path}`]\n"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"[Could not read `{path}`: {e!s}]\n"
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[... truncated by CHAINLIT_SKILL_PER_FILE_MAX ...]\n"
    return text


def _pipeline_keywords(text: str) -> bool:
    """User asked for the full multi-stage QA workflow (needs many MCP rounds)."""
    t = text.lower()
    if any(
        k in t
        for k in (
            "full pipeline",
            "complete qa workflow",
            "complete workflow",
            "run complete workflow",
            "full workflow",
            "run workflow",
            "run the workflow",
            "workflow for",
            "planner through healer",
            "run the qa pipeline",
            "execute the full workflow",
            "start qa automation",
            "qa automation for",
            "e2e workflow",
        )
    ):
        return True
    # Short prompts like "Run workflow for PROJ-123" (Jira key + workflow intent).
    if _looks_like_jira_issue_key(text or "") and any(
        h in t for h in ("run workflow", "workflow for", "qa pipeline", "full qa")
    ):
        return True
    return False


def _effective_mcp_max_rounds(user_text: str) -> int:
    """Default 24; full-workflow phrases raise the cap (default 48) so Planner→Healer can finish."""
    base = int(os.getenv("CHAINLIT_MCP_MAX_ROUNDS", "24"))
    base = max(1, min(base, 200))
    if _pipeline_keywords(user_text):
        wf = int(os.getenv("CHAINLIT_MCP_MAX_ROUNDS_WORKFLOW", "48"))
        wf = max(1, min(wf, 200))
        return max(base, wf)
    return base


def _effective_chat_total_timeout(user_text: str) -> float:
    """Longer wall-clock budget when the user asks for a full workflow (many MCP + LLM turns)."""
    base = float(os.getenv("CHAINLIT_CHAT_TOTAL_TIMEOUT", "240"))
    if _pipeline_keywords(user_text):
        wf = float(os.getenv("CHAINLIT_CHAT_TOTAL_TIMEOUT_WORKFLOW", "900"))
        return max(base, wf)
    return base


def _session_chat_setting(key: str) -> str | None:
    """Values from Chainlit Chat Settings (gear / sidebar); set in ``@cl.on_chat_start``."""
    try:
        sess = context.session
        if hasattr(sess, "chat_settings") and isinstance(sess.chat_settings, dict):
            v = sess.chat_settings.get(key)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
    except Exception:
        pass
    return None


def _parse_ui_model_choices() -> list[str]:
    raw = os.getenv("CHAINLIT_UI_MODEL_CHOICES", "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return [
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "o3-mini",
        "o4-mini",
    ]


def _ui_model_select_config() -> tuple[list[str], str]:
    """Model dropdown: optional comma list in env; current ``CHAINLIT_OPENAI_MODEL`` is always included."""
    models = _parse_ui_model_choices()
    if not models:
        models = ["gpt-4.1", "gpt-4o"]
    default = (os.getenv("CHAINLIT_OPENAI_MODEL") or "gpt-4.1").strip() or "gpt-4.1"
    if default not in models:
        models = [default] + models
    return models, default


def _resolve_skill_profile() -> str:
    """Chat setting ``chainlit_skill_profile`` overrides ``CHAINLIT_SKILL_PROFILE`` unless UI is Auto."""
    ui = _session_chat_setting("chainlit_skill_profile")
    if ui:
        ui_l = ui.strip().lower()
        if ui_l != "auto":
            return ui_l
    return os.getenv("CHAINLIT_SKILL_PROFILE", "auto").strip().lower()


def _session_openai_model() -> str:
    return _session_chat_setting("chainlit_openai_model") or os.getenv("CHAINLIT_OPENAI_MODEL", "gpt-4.1")


def _is_openai_setup_starter_message(text: str) -> bool:
    """True when the user sent the Chainlit Setup «OpenAI / LLM check» starter (verbatim paste)."""
    t = (text or "").strip()
    if len(t) < 80:
        return False
    low = re.sub(r"[*_`]+", "", t.lower())
    for dash in ("\u2014", "\u2013", "—", "–"):
        low = low.replace(dash, "-")
    if not low.startswith("setup - openai:"):
        return False
    return "openai_api_key" in low and "step" in low and "3" in low


def _skill_path_routing_blob(thread_h: str, current_user_text: str) -> str:
    """Narrow skill routing to the current line when it is only the OpenAI setup starter."""
    if _is_openai_setup_starter_message(current_user_text):
        return current_user_text
    return thread_h


def _all_stage_skill_paths() -> list[Path]:
    root = _PROJECT_ROOT / ".github" / "skills"
    return [
        root / "planner" / "SKILL.md",
        root / "planner" / "gap-analysis-checklist.md",
        root / "qase-designer" / "SKILL.md",
        root / "qase-designer" / "test-design-checklist.md",
        root / "qase-designer" / "feasibility-checklist.md",
        root / "automation" / "SKILL.md",
        root / "automation" / "script-generation-checklist.md",
        root / "executor" / "SKILL.md",
        root / "executor" / "execution-checklist.md",
        root / "healer" / "SKILL.md",
        root / "healer" / "failure-analysis-checklist.md",
    ]


def _select_skill_paths(user_text: str) -> list[Path]:
    """Paths to `.github/skills` and `.github/rules` markdown, ordered and deduped."""
    explicit = os.getenv("CHAINLIT_SKILL_FILES", "").strip()
    if explicit:
        paths = [_resolve_repo_path(part) for part in explicit.split(",") if part.strip()]
        return _dedupe_paths(paths)

    profile = _resolve_skill_profile()
    orch = _PROJECT_ROOT / ".github" / "skills" / "orchestrator" / "SKILL.md"
    mcp_rule = _PROJECT_ROOT / ".github" / "rules" / "mcp-usage.md"
    base = [orch, mcp_rule]
    stages = _all_stage_skill_paths()

    if profile == "orchestrator":
        return _dedupe_paths(base)
    if profile == "full":
        return _dedupe_paths(base + stages)
    if profile == "planner":
        return _dedupe_paths(base + stages[0:2])
    if profile == "qase-designer":
        return _dedupe_paths(base + stages[2:5])
    if profile == "automation":
        return _dedupe_paths(base + stages[5:7])
    if profile == "executor":
        return _dedupe_paths(base + stages[7:9])
    if profile == "healer":
        return _dedupe_paths(base + stages[9:11])

    # auto (default): base + heuristics
    extra: list[Path] = []
    if _pipeline_keywords(user_text):
        return _dedupe_paths(base + stages)
    if _looks_like_jira_issue_key(user_text):
        extra.extend(stages[0:2])
    if _user_mentions_qase(user_text):
        extra.extend(stages[2:5])
    return _dedupe_paths(base + extra)


def _effective_skill_limits(user_text: str) -> tuple[int, int]:
    """(per_file, total) chars — tighter defaults for full-workflow prompts to leave room for MCP history."""
    per = int(os.getenv("CHAINLIT_SKILL_PER_FILE_MAX", "16000"))
    total = int(os.getenv("CHAINLIT_SKILLS_MAX_CHARS", "50000"))
    if _pipeline_keywords(user_text):
        per = int(os.getenv("CHAINLIT_SKILL_PER_FILE_MAX_WORKFLOW", "12000"))
        total = int(os.getenv("CHAINLIT_SKILLS_MAX_CHARS_WORKFLOW", "22000"))
    return max(2000, per), max(8000, total)


def _build_skill_context_for_openai(thread_h: str, current_user_text: str) -> tuple[str, list[str]]:
    """Markdown skill bundle for the system prompt + relative paths (for optional logging)."""
    if _env_truthy("CHAINLIT_DISABLE_SKILLS", default=False):
        return "", []
    if _is_openai_setup_starter_message(current_user_text):
        return "", []

    per_file, total_max = _effective_skill_limits(thread_h)
    paths = _select_skill_paths(_skill_path_routing_blob(thread_h, current_user_text))
    rel_labels = []
    try:
        rel_labels = [str(p.relative_to(_PROJECT_ROOT)) for p in paths]
    except ValueError:
        rel_labels = [str(p) for p in paths]

    parts: list[str] = [_CHAINLIT_SKILL_ADAPTATION, "", "---", ""]
    used = sum(len(x) for x in parts)

    for p in paths:
        rel = str(p.relative_to(_PROJECT_ROOT)) if p.is_relative_to(_PROJECT_ROOT) else str(p)
        chunk = _read_skill_file(p, per_file)
        block = f"### Skill / rule: `{rel}`\n\n{chunk}"
        if used + len(block) > total_max:
            remain = total_max - used - 80
            if remain > 200:
                parts.append(block[:remain] + "\n\n[... skill bundle truncated: CHAINLIT_SKILLS_MAX_CHARS ...]\n")
            break
        parts.append(block)
        parts.append("")
        used += len(block) + 1

    return "\n".join(parts).strip(), rel_labels


async def _probe_openai_reachable(client: AsyncOpenAI) -> str | None:
    """Quick call to fail fast if the API is unreachable (returns error text or None if OK)."""
    if os.getenv("CHAINLIT_SKIP_OPENAI_PROBE", "").lower() in ("1", "true", "yes"):
        return None
    probe_timeout = float(os.getenv("CHAINLIT_OPENAI_PROBE_TIMEOUT", "20"))
    try:
        await asyncio.wait_for(client.models.list(), timeout=probe_timeout)
        return None
    except Exception as e:
        return _format_connect_exception(e)


# Jira / JSM issue keys: PROJECT-123 (Atlassian-style).
_JIRA_ISSUE_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")


def _jira_key_excluded_upper_projects() -> set[str]:
    """Prefixes excluded from “looks like Jira” detection (false positives).

    **TC-356**-style tokens are often **Qase** (or other) test-case ids, not Jira. Default excludes project
    key **TC**. If your Jira site has a real **TC** project, set ``CHAINLIT_JIRA_KEY_EXCLUDE_PROJECTS=`` to
    empty in `.env`, or set a comma list that omits **TC**.
    """
    raw = os.getenv("CHAINLIT_JIRA_KEY_EXCLUDE_PROJECTS")
    if raw is None:
        return {"TC"}
    if not raw.strip():
        return set()
    return {p.strip().upper() for p in raw.split(",") if p.strip()}


def _jira_issue_key_matches_upper(text: str) -> list[re.Match[str]]:
    """``PROJECT-123`` matches in uppercased *text*, skipping excluded project prefixes."""
    excl = _jira_key_excluded_upper_projects()
    out: list[re.Match[str]] = []
    for m in _JIRA_ISSUE_KEY_RE.finditer(text.upper()):
        proj = m.group(0).split("-", 1)[0]
        if proj in excl:
            continue
        out.append(m)
    return out


# Qase UI/public ids often look like **TC-356**; steer away from Jira **getJiraIssue**.
_QASE_TC_STYLE_ID_RE = re.compile(r"\bTC-\d+\b", re.IGNORECASE)


def _qase_tc_id_user_hint_suffix(visible: str) -> str:
    if not _QASE_TC_STYLE_ID_RE.search(visible):
        return ""
    return (
        "\n\n[Qase: identifiers like **TC-356** — use **`get_case`** (Qase MCP; exact tool `name` in this session); "
        "do **not** call **getJiraIssue**.]"
    )


def _user_text_from_chainlit(content: Any) -> str:
    """Chainlit may pass str or structured content for multimodal messages."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    parts.append(str(block["text"]))
                else:
                    parts.append(json.dumps(block, default=str))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return "" if content is None else str(content)


def _looks_like_jira_issue_key(text: str) -> bool:
    return bool(_jira_issue_key_matches_upper(text))


# Docs / template keys shipped in starter text — never treat as the user's real issue.
_STARTER_DOCS_PLACEHOLDER_JIRA = frozenset({"PROJ-123"})


def _concrete_jira_key_from_text(text: str) -> str | None:
    """First Jira issue key in ``text`` that is not a known template placeholder (e.g. PROJ-123)."""
    for m in _jira_issue_key_matches_upper((text or "").upper()):
        k = m.group(0)
        if k not in _STARTER_DOCS_PLACEHOLDER_JIRA:
            return k
    return None


def _starter_needs_jira_prompt(user_text: str) -> bool:
    """True for pipeline / stage starters that require a real Jira issue before calling the model."""
    if _is_openai_setup_starter_message(user_text):
        return False
    if _message_triggers_local_mcp_probe(user_text):
        return False
    if not (user_text or "").strip():
        return False
    if _pipeline_keywords(user_text):
        return True
    low = user_text.lower()
    markers = (
        "full human-loop qa pipeline",
        "**orchestrator:**",
        "orchestrator:",
        "**planner only:**",
        "planner only:",
        "**qase designer only:**",
        "qase designer only:",
        "**automation only:**",
        "automation only:",
    )
    return any(m in low for m in markers)


def _starter_is_automation_only(user_text: str) -> bool:
    low = (user_text or "").lower()
    return "**automation only:**" in low or "automation only:" in low


def _valid_user_supplied_jira_key(key: str) -> bool:
    k = (key or "").strip().upper()
    if not k:
        return False
    m = _JIRA_ISSUE_KEY_RE.search(k)
    if not m:
        return False
    return m.group(0) not in _STARTER_DOCS_PLACEHOLDER_JIRA


_FEATURE_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def _valid_feature_slug(slug: str) -> bool:
    s = (slug or "").strip().lower()
    return bool(s and _FEATURE_SLUG_RE.match(s))


async def _prompt_starter_inputs_if_needed(user_text: str) -> str | None:
    """For workflow starters, collect Jira key (and automation feature slug) via UI. Returns None to abort."""
    if not _env_truthy("CHAINLIT_STARTER_INPUT_PROMPTS", default=True):
        return user_text
    if not _starter_needs_jira_prompt(user_text):
        return user_text

    tmo = max(30, min(int(os.getenv("CHAINLIT_STARTER_INPUT_TIMEOUT", "300")), 3600))
    out = user_text.rstrip()
    extra: list[str] = []

    if _concrete_jira_key_from_text(user_text) is None:
        res = await cl.AskUserMessage(
            content=(
                "**Input required — Jira issue**\n\n"
                "Paste the **Jira issue key** for this run (`PROJECT-123`, e.g. `GPS-7525`). "
                "Send **only** the key on one line."
            ),
            timeout=tmo,
            raise_on_timeout=False,
        ).send()
        key = ""
        if res and isinstance(res, dict):
            key = str(res.get("output") or "").strip()
        if not _valid_user_supplied_jira_key(key):
            await cl.Message(
                content="**Cancelled.** A valid Jira issue key is required to start this workflow (template keys like `PROJ-123` are not accepted).",
            ).send()
            return None
        extra.append(f"**Jira issue for this run:** {key.strip().upper()}")

    if _starter_is_automation_only(user_text):
        res2 = await cl.AskUserMessage(
            content=(
                "**Input required — feature folder**\n\n"
                "Enter a short **feature slug** for `tests/<feature>/` (kebab-case, e.g. `user-login`). "
                "Letters, numbers, and hyphens only."
            ),
            timeout=tmo,
            raise_on_timeout=False,
        ).send()
        slug = ""
        if res2 and isinstance(res2, dict):
            slug = str(res2.get("output") or "").strip()
        if not _valid_feature_slug(slug):
            await cl.Message(
                content="**Cancelled.** A valid feature slug is required for the Automation starter (e.g. `login-flow`).",
            ).send()
            return None
        extra.append(f"**Feature folder slug:** `{slug.strip().lower()}`")

    if not extra:
        return user_text
    return out + "\n\n" + "\n".join(extra)


def _issue_key_from_jira_mcp_args(args: dict[str, Any]) -> str | None:
    """Normalize PROJ-123 from getJiraIssue args so equivalent calls share one cache key."""
    for k in ("issueIdOrKey", "issueKey", "issueKeyOrId", "key"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            m = _JIRA_ISSUE_KEY_RE.search(v.upper())
            if m:
                return m.group(0)
            return v.strip().upper()
    return None


def _jira_comment_body_from_args(args: dict[str, Any]) -> str:
    """Atlassian MCP often uses ``commentBody``; older shapes use ``body`` / ``comment``."""
    return str(
        args.get("body")
        or args.get("comment")
        or args.get("commentBody")
        or args.get("comment_body")
        or ""
    )


def _register_jira_get_fetched_if_ok(
    real_name: str, args: dict[str, Any], tool_text: str, store: set[str]
) -> None:
    """Track issue keys that successfully returned from getJiraIssue (enables addComment gating)."""
    if real_name != "getJiraIssue":
        return
    ts = str(tool_text)
    if ts.startswith("MCP call_tool error"):
        return
    if "(MCP operation reported isError)" in ts[:500]:
        return
    ik = _issue_key_from_jira_mcp_args(args)
    if ik:
        store.add(ik.upper())


def _first_jira_key_in_text(text: str) -> str | None:
    m = _JIRA_ISSUE_KEY_RE.search(text)
    return m.group(0).upper() if m else None


def _last_jira_key_in_text(text: str) -> str | None:
    matches = list(_JIRA_ISSUE_KEY_RE.finditer(text.upper()))
    return matches[-1].group(0).upper() if matches else None


def _heuristic_require_jira_fetch_tools(user_text: str, thread_h: str) -> bool:
    """When a Jira key is present, require MCP tools for prompts that need real issue data.

    Originally matched only explicit *fetch* phrasing; phrases like **Qase test design for PROJ-123** left
    ``tool_choice`` on **auto**, so models often returned narration-only replies and **no** ``tool_calls`` —
    the handler then returned that text immediately and **no MCP ran** (looks like a broken flow).
    """
    blob = f"{user_text}\n{thread_h}".strip()
    if not _looks_like_jira_issue_key(blob):
        return False
    lo = blob.lower()
    if re.search(r"\bfetch\b", lo):
        return True
    if any(
        ph in lo
        for ph in (
            "get issue",
            "get jira",
            "show issue",
            "load issue",
            "pull issue",
            "retrieve issue",
            "issue details",
            "jira details",
            "open issue",
        )
    ):
        return True
    # Qase designer / pipeline / analysis threads need Jira facts for the cited key.
    if _user_mentions_qase(blob) or _thread_mentions_qase_stage_work(blob):
        return True
    if _pipeline_keywords(blob):
        return True
    if any(
        ph in lo
        for ph in (
            "test design",
            "test cases for",
            "design test case",
            "design test cases",
            "gap analysis",
            "requirement analysis",
            "acceptance criteria",
            "test readiness",
            "planner output",
            "planner stage",
        )
    ):
        return True
    return False


def _openai_tool_name_for_mcp_operation(
    routing: dict[str, tuple[str, str]], operation: str
) -> str | None:
    keys = [oai for oai, (_mcp, real) in routing.items() if real == operation]
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0]
    keys.sort(key=lambda k: (_mcp_ui_bucket(routing[k][0]) != "jira", k))
    return keys[0]


def _routing_keys_for_operation_ci(routing: dict[str, tuple[str, str]], operation: str) -> list[str]:
    """Keys whose MCP operation name matches ``operation`` (case-insensitive)."""
    if not operation or not routing:
        return []
    want = operation.strip().lower()
    return [k for k, (_m, op) in routing.items() if isinstance(op, str) and op.lower() == want]


def _resolve_mcp_tool_routing_key(
    fn: str,
    routing: dict[str, tuple[str, str]],
) -> str | None:
    """Map the model's tool name to the key used in ``routing``.

    OpenAI tools are registered as ``<mcp_connection>__<operation>``, but the model often
    emits the bare MCP operation (e.g. ``getJiraIssue``) because skills and prompts name
    it that way — which would otherwise produce ``Unknown MCP routing entry``.
    """
    if not fn or not routing:
        return None
    s = fn.strip()
    if s in routing:
        return s

    def _pick_ambiguous(keys: list[str]) -> str | None:
        if not keys:
            return None
        if len(keys) == 1:
            return keys[0]
        keys.sort(key=lambda k: (_mcp_ui_bucket(routing[k][0]) != "jira", k))
        return keys[0]

    # Models often emit "user-atlassian.getJiraIssue" (dot). Keys use "conn__op" (double underscore).
    # Connection labels may use hyphens in docs but underscores in Chainlit (user-atlassian vs user_atlassian).
    if "." in s:
        dot_as_sep = s.replace(".", "__")
        variants: list[str] = [dot_as_sep, dot_as_sep.replace("-", "_")]
        if "__" in dot_as_sep:
            pref, _, suf = dot_as_sep.rpartition("__")
            slug = re.sub(r"[^a-zA-Z0-9_]", "_", pref.replace("-", "_").replace(".", "_"))
            variants.append(f"{slug}__{suf}")
        seen_v: set[str] = set()
        for v in variants:
            if not v or v in seen_v:
                continue
            seen_v.add(v)
            if v in routing:
                return v
        tail_dot = s.rsplit(".", 1)[-1]
        if tail_dot:
            hit = _pick_ambiguous(_routing_keys_for_operation_ci(routing, tail_dot))
            if hit:
                return hit

    if "__" in s:
        tail = s.rsplit("__", 1)[-1]
        if tail:
            hit = _pick_ambiguous(_routing_keys_for_operation_ci(routing, tail))
            if hit:
                return hit

    hit = _pick_ambiguous(_routing_keys_for_operation_ci(routing, s))
    if hit:
        return hit
    slo = s.lower()
    hit = _pick_ambiguous([k for k, (_m, op) in routing.items() if isinstance(op, str) and op.lower() == slo])
    if hit:
        return hit
    # One underscore or other separators (model guessed "Rovo_MCP_getJiraIssue").
    if slo.endswith("getjiraissue") and slo != "getjiraissue":
        return _pick_ambiguous(_routing_keys_for_operation_ci(routing, "getJiraIssue"))
    return None


def _is_status_noise_assistant_message(content: str) -> bool:
    """Strip Chainlit status pings from thread history so the model sees real Q&A."""
    c = (content or "").strip()
    if not c:
        return True
    if c.startswith("**Step 1/3:**"):
        return True
    if c.startswith("OpenAI reachable. Discovering callable"):
        return True
    if c.startswith("**OpenAI reachable.**"):
        return True
    if c.startswith("**Full-workflow request:**"):
        return True
    if c.startswith("**Skill context:**"):
        return True
    if c.startswith("**Step 2/3:**"):
        return True
    if c.startswith("**Step 3/3:**"):
        return True
    return False


def _heuristic_thread_text(current_user: str) -> str:
    """Recent Chainlit thread text for skill routing, timeouts, and Jira key detection."""
    try:
        rows = chat_context.to_openai()
    except Exception:
        return current_user
    parts: list[str] = []
    for m in rows:
        c = m.get("content")
        if not isinstance(c, str) or not c.strip():
            continue
        if m.get("role") == "assistant" and _is_status_noise_assistant_message(c):
            continue
        parts.append(c.strip())
    blob = "\n".join(parts)
    max_c = max(2000, int(os.getenv("CHAINLIT_HEURISTIC_THREAD_MAX_CHARS", "16000")))
    if len(blob) > max_c:
        blob = blob[-max_c:]
    return blob if blob else current_user


def _chainlit_thread_openai_rows() -> list[dict[str, Any]]:
    """Prior user/assistant turns for OpenAI ``messages`` (current user line is appended separately)."""
    try:
        rows = chat_context.to_openai()
    except Exception:
        return []
    if not rows:
        return []
    if rows[-1].get("role") == "user":
        rows = rows[:-1]
    max_m = max(0, int(os.getenv("CHAINLIT_THREAD_HISTORY_MAX_MESSAGES", "48")))
    if len(rows) > max_m:
        rows = rows[-max_m:]
    out: list[dict[str, Any]] = []
    for m in rows:
        role = m.get("role")
        c = m.get("content")
        if not isinstance(c, str) or not c.strip():
            continue
        if role == "assistant" and _is_status_noise_assistant_message(c):
            continue
        if role not in ("user", "assistant"):
            continue
        out.append({"role": role, "content": c})
    return out


def _is_gap_analysis_focus(user_text: str) -> bool:
    """Planner / gap / requirement analysis (not full multi-stage workflow)."""
    if _pipeline_keywords(user_text):
        return False
    blob = _heuristic_thread_text(user_text)
    # Chat Settings chose a concrete skill pack — not ad-hoc gap / strip-getJira heuristics.
    if _resolve_skill_profile() != "auto":
        return False
    if not _looks_like_jira_issue_key(blob):
        return False
    t = user_text.lower()
    return any(
        k in t
        for k in (
            "gap",
            "requirement",
            "readiness",
            "analysis",
            "gap analysis",
            "test readiness",
            "requirement analysis",
            # Note: do not match "planner" alone — it collides with "Planner agent" / UI wording.
            "planner output",
            "planner stage",
        )
    )


def _strip_get_jira_issue_tools(
    tool_specs: list[Any],
    routing: dict[str, tuple[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Remove getJiraIssue from what the model can call (linked issues: use JQL)."""
    specs = _normalize_tool_specs_dicts(tool_specs)
    new_routing = {k: v for k, v in routing.items() if v[1] != "getJiraIssue"}
    keep = set(new_routing.keys())
    new_specs = [t for t in specs if _openai_tool_spec_function_name(t) in keep]
    return new_specs, new_routing


def _jira_cloud_id_from_env() -> str:
    """Atlassian Cloud ID for MCP `cloudId` when Rovo discovery is empty or confusing."""
    return (os.getenv("JIRA_CLOUD_ID") or os.getenv("ATLASSIAN_CLOUD_ID") or "").strip()


_ATLASSIAN_CLOUD_ID_PLACEHOLDERS = frozenset(
    {
        "{cloudid}",
        "<cloudid>",
        "${cloudid}",
        "your_cloud_id",
        "your-cloud-id",
        "your cloud id",
    }
)


def _normalize_atlassian_cloud_id_in_args(args: dict[str, Any]) -> None:
    """If the model sends documentation placeholders (e.g. ``{cloudId}``) or leaves ``cloudId`` empty, substitute
    ``JIRA_CLOUD_ID`` / ``ATLASSIAN_CLOUD_ID`` from `.env` when set. Prevents Atlassian MCP errors like
    "Failed to fetch cloud ID for: {cloudId}".

    **Call only for Jira/Atlassian MCP tools** — never for Qase or other servers (would leak Jira UUID into Qase APIs).
    """
    cid_env = _jira_cloud_id_from_env()
    if not cid_env:
        return
    raw = args.get("cloudId")
    if raw is None:
        args["cloudId"] = cid_env
        return
    if not isinstance(raw, str):
        return
    s = raw.strip()
    if not s:
        args["cloudId"] = cid_env
        return
    if s.lower() in _ATLASSIAN_CLOUD_ID_PLACEHOLDERS:
        args["cloudId"] = cid_env
        return
    if len(s) >= 2 and s[0] == "{" and s[-1] == "}" and "cloud" in s.lower():
        args["cloudId"] = cid_env


def _strip_jira_leakage_from_qase_mcp_args(args: dict[str, Any]) -> list[str]:
    """Models (and older Chainlit behavior) sometimes send Jira ``cloudId`` / ``issueIdOrKey`` on Qase tools.

    Qase MCP schemas use ``additionalProperties: false`` for many operations; extra keys can confuse APIs.
    Returns removed key names for optional logging.
    """
    removed: list[str] = []
    if not isinstance(args, dict):
        return removed
    # Normalized key forms (ignore underscores / case).
    jira_only_norm = frozenset(
        {
            "cloudid",
            "issueidorkey",
            "issueid",
            "jirakey",
            "jiraissuekey",
            "atlassiancloudid",
            "atlcloudid",
        }
    )
    for k in list(args.keys()):
        if not isinstance(k, str):
            continue
        norm = k.lower().replace("_", "")
        if norm in jira_only_norm:
            args.pop(k, None)
            removed.append(k)
    return removed


def _force_env_jira_cloud_id_for_atlassian_mcp(args: dict[str, Any], mcp_conn: str) -> None:
    """If ``JIRA_CLOUD_ID`` / ``ATLASSIAN_CLOUD_ID`` is set, use it for Atlassian/Jira MCP ``cloudId``.

    The model often sends **wrong but syntactically valid** UUIDs (invented or copied from unrelated APIs),
    which yields errors like **No organization ID found for cloud ID**. Qase and other connections are
    unchanged — only connections classified as Jira/Atlassian (see ``_mcp_ui_bucket``).
    """
    if not isinstance(args, dict):
        return
    if _mcp_ui_bucket(mcp_conn) != "jira":
        return
    if not _env_truthy("CHAINLIT_FORCE_JIRA_CLOUD_ID_FROM_ENV", default=True):
        return
    cid = _jira_cloud_id_from_env()
    if not cid:
        return
    cur = args.get("cloudId")
    if not isinstance(cur, str) or cur.strip() != cid:
        args["cloudId"] = cid


def _jira_cloud_id_env_prompt_block() -> str:
    """Inject configured cloud ID so the model does not ask the user when `.env` already has it."""
    if not _env_truthy("CHAINLIT_INJECT_JIRA_CLOUD_ID", default=True):
        return ""
    cid = _jira_cloud_id_from_env()
    if not cid:
        return ""
    return (
        "\n\n**`JIRA_CLOUD_ID` / `ATLASSIAN_CLOUD_ID` (from server `.env`):** For **every** Jira/Atlassian MCP call "
        f"that needs **`cloudId`**, use **exactly** `{cid}` — **never** invent, guess, or reuse UUIDs from Qase or "
        "other products. **`cloudId` is not a Qase field** — do **not** pass it to **`create_case`**, **`create_plan`**, "
        "or any **`user-qase`** tool. **Do not** call **getAccessibleAtlassianResources** for discovery when this is already set. "
        "Do **not** ask the user for a cloud ID."
    )


def _user_message_with_jira_mcp_instructions(raw: str) -> str:
    """Steer the model to Atlassian/Jira via MCP only (no invented URLs)."""
    if not _looks_like_jira_issue_key(raw):
        return raw
    cid = ""
    if _env_truthy("CHAINLIT_INJECT_JIRA_CLOUD_ID", default=True):
        cid = _jira_cloud_id_from_env()
    if cid:
        cloud_line = (
            f"If **cloudId** is required, use **`cloudId` = `{cid}`** from server `.env` — **do not** call "
            "**getAccessibleAtlassianResources** for discovery first. "
        )
    else:
        cloud_line = (
            "If **cloudId** is required, call **getAccessibleAtlassianResources** once, then **getJiraIssue**. "
        )
    base = (
        raw.rstrip()
        + "\n\n[Instructions: Answer using **MCP only** — call the **getJiraIssue** function from this request's "
        "**tools** list using its exact **`function.name`** (Chainlit prefixes it with the MCP connection id). "
        "**Do not** ask the user for connection names, prefixes, or tool strings — never tell them to open the MCP "
        "panel to copy names. "
        + cloud_line
        + "Do **not** tell the user to open a browser, do **not** fabricate `https://…atlassian.net/browse/…` links, "
        "and never use placeholder hosts such as **your-jira-instance**. Summarize from the MCP result text/JSON "
        "(summary, status, description, assignee).]"
    )
    return base


def _user_mentions_qase(text: str) -> bool:
    return "qase" in text.lower()


def _thread_mentions_qase_stage_work(text: str) -> bool:
    """Phrases that imply Qase designer / test artifacts (even without the word 'qase')."""
    t = text.lower()
    return any(
        k in t
        for k in (
            "qase designer",
            "design test case",
            "design test cases",
            "test case design",
            "test cases in qase",
            "create suite",
            "create case",
            "test suite",
            "feasibility analysis",
            "automation feasibility",
            "store in qase",
            "qase project",
            "list projects",
            "create plan",
        )
    )


def _should_keep_qase_tools_with_jira_thread(thread_h: str) -> bool:
    """Do not strip Qase from the tool list when the workflow needs both Jira and Qase."""
    if _pipeline_keywords(thread_h):
        return True
    if _user_mentions_qase(thread_h):
        return True
    if _thread_mentions_qase_stage_work(thread_h):
        return True
    return False


def _workflow_env_hints() -> str:
    """Non-secret defaults from `.env` so the model avoids placeholder MCP args (Qase `code`, GitHub owner/repo)."""
    if not _env_truthy("CHAINLIT_WORKFLOW_ENV_HINTS", default=True):
        return ""
    parts: list[str] = []
    url = (
        os.getenv("CHAINLIT_TEST_BASE_URL")
        or os.getenv("QASE_TEST_BASE_URL")
        or os.getenv("BASE_URL")
        or ""
    ).strip()
    if url:
        parts.append(
            f"[Default app URL from `.env` (`BASE_URL` / `CHAINLIT_TEST_BASE_URL` / `QASE_TEST_BASE_URL`): **{url}** — "
            "use for Playwright navigation and Qase preconditions when Jira text does not specify another URL.]"
        )
    qase_code = (os.getenv("QASE_PROJECT_CODE") or os.getenv("QASE_PROJECT") or "").strip()
    if qase_code:
        parts.append(
            f"[Qase project **`code`** from `.env`: **{qase_code}** — use in **`create_run`**, **`create_case`**, "
            "**`list_cases`**, etc. Do **not** send schema placeholders like `your_project_code`. "
            "If this code fails validation, call Qase **`list_projects`** once and use the exact `code` from the response.]"
        )
    gh_o, gh_r = _resolved_github_owner_repo()
    if gh_o and gh_r:
        parts.append(
            f"[GitHub **owner** / **repo** for this Chainlit app (resolved for **`create_pull_request`**, PRs, files): "
            f"**{gh_o}** / **{gh_r}**. "
            "By default **`git remote origin`** wins over `.env` when both exist (fixes truncated `GITHUB_REPOSITORY`). "
            "If you need `.env` to override `origin`, set **`CHAINLIT_GITHUB_REPOSITORY_TRUST_ENV=1`**. "
            "If there is no git metadata, fall back to `GITHUB_REPOSITORY` / split env vars. "
            f"**Automation JSON `pr_url`:** `https://github.com/{gh_o}/{gh_r}/pull/<pr_number>` only — "
            "do **not** paste example repos from docs unless they match **this** `origin`. "
            "**`repo`** must match the exact GitHub slug. Verify PAT with **`get_me`**; discover with **`search_repositories`**.]"
        )
    if not parts:
        return ""
    return "\n\n" + " ".join(parts)


def _user_message_with_qase_instructions(raw: str, thread_h: str) -> str:
    """Steer the model to Qase MCP; combined hints when Jira + Qase are both in play."""
    s = raw.rstrip()
    tc_suff = _qase_tc_id_user_hint_suffix(s)
    if _pipeline_keywords(thread_h):
        return (
            s
            + "\n\n[Full QA pipeline: use **Atlassian MCP** for Jira issue data and **Qase MCP** for test management "
            "(suites/cases/plans — operation names may be prefixed). **Creating test artifacts requires calling Qase "
            "MCP tools** (e.g. create_case, create_suite, list_projects as exposed); Jira `addComment` is not a "
            "substitute for Qase case creation.]"
            + tc_suff
        )
    if _user_mentions_qase(raw) and not _thread_mentions_qase_stage_work(thread_h):
        return (
            s
            + "\n\n[This message is about **Qase** (test management). Use the **Qase MCP** connection (operation names "
            "may be prefixed) — e.g. list/get projects per the MCP operation descriptions. Do **not** refuse without "
            "calling an MCP operation first. If MCP returns an error, quote it verbatim.]"
            + tc_suff
        )
    if _thread_mentions_qase_stage_work(thread_h):
        return (
            s
            + "\n\n[This thread is in a **Qase test-design** stage: call **Qase MCP** to create or list real test "
            "artifacts; use Atlassian MCP only for Jira issue data.]"
            + tc_suff
        )
    if tc_suff:
        return s + tc_suff
    return raw


def _qase_api_token_in_env() -> bool:
    return bool((os.getenv("QASE_API_TOKEN") or os.getenv("QASE_TOKEN") or "").strip())


def _routing_has_qase_tools(routing: dict[str, tuple[str, str]]) -> bool:
    return any(_mcp_connection_or_op_is_qase(mcp, op) for mcp, op in routing.values())


def _mcp_name_looks_like_qase(mcp_name: str) -> bool:
    """Chainlit MCP connection names are user-defined; Qase servers usually contain 'qase'."""
    return "qase" in mcp_name.lower()


def _mcp_connection_or_op_is_qase(mcp_conn: str, operation: str) -> bool:
    return _mcp_name_looks_like_qase(mcp_conn) or _is_qase_mcp_operation(operation)


def _looks_like_qase_tc_public_id(issue_key: str) -> bool:
    """Qase shows ids like **TC-377**; these are not Jira keys — do not call ``getJiraIssue`` with them."""
    s = (issue_key or "").strip()
    if not s:
        return False
    s = s.replace("\u2212", "-").replace("–", "-").replace("—", "-")
    return bool(re.match(r"(?i)^TC-\d+$", s))


def _raw_jira_issue_selector_from_args(args: dict[str, Any]) -> str:
    """Issue id/key as the model sent it (any common parameter name). Used before Jira API calls."""
    for k in ("issueIdOrKey", "issueKey", "issueKeyOrId", "key", "issue_id", "issueID"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, int):
            return str(v)
    return ""


def _real_name_is_get_jira_issue(name: str) -> bool:
    if not isinstance(name, str):
        return False
    n = name.lower().replace("-", "").replace("_", "")
    return n == "getjiraissue"


def _mcp_ui_bucket(mcp_conn: str) -> str:
    """Group MCP connections for Chainlit labels (Jira vs Qase vs other)."""
    n = mcp_conn.lower()
    if "qase" in n:
        return "qase"
    if "atlassian" in n or "rovo" in n or "jira" in n:
        return "jira"
    return "other"


def _effective_mcp_display_bucket(mcp_conn: str, real_name: str) -> str:
    """Treat known Qase tool names as Qase even when the MCP connection id omits ``qase`` (e.g. ``@qase/mcp-server``)."""
    b = _mcp_ui_bucket(mcp_conn)
    if b in ("jira", "qase"):
        return b
    if _is_qase_mcp_operation(real_name):
        return "qase"
    return b


def _mcp_tool_hint_fragment(mcp_conn: str, real_name: str, args: dict[str, Any]) -> str:
    """Short, non-secret hint for step titles (issue key, case title, project code, etc.)."""
    bucket = _effective_mcp_display_bucket(mcp_conn, real_name)
    if bucket == "jira":
        if real_name == "getJiraIssue":
            ik = _issue_key_from_jira_mcp_args(args)
            if ik:
                return f" · {ik}"
        if real_name == "addCommentToJiraIssue":
            body = _jira_comment_body_from_args(args).strip()
            if body:
                return f" · {body[:72]}{'…' if len(body) > 72 else ''}"
        for k in ("issueIdOrKey", "issueKey", "key"):
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                return f" · {v.strip()[:48]}"
    if bucket == "qase":
        for k in ("title", "name", "code", "case_id", "id", "suite_id", "project", "project_code"):
            v = args.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return f" · {s[:72]}"
    return ""


def _mcp_chainlit_step_title(
    mcp_conn: str,
    real_name: str,
    args: dict[str, Any],
    *,
    suffix: str = "",
) -> str:
    """Human-readable labels: ``Jira · …`` / ``Qase · …`` so Qase matches Jira visibility in the chat."""
    hint = _mcp_tool_hint_fragment(mcp_conn, real_name, args)
    bucket = _effective_mcp_display_bucket(mcp_conn, real_name)
    if bucket == "qase":
        base = f"Qase · {real_name}{hint}"
    elif bucket == "jira":
        base = f"Jira · {real_name}{hint}"
    else:
        base = f"MCP · {mcp_conn} · {real_name}"
    return f"{base}{suffix}".strip()


def _mcp_chainlit_step_tags(mcp_conn: str, base: list[str], real_name: str = "") -> list[str]:
    out = list(dict.fromkeys([*base, "mcp"]))
    b = _effective_mcp_display_bucket(mcp_conn, real_name)
    if b == "qase" and "qase" not in out:
        out.append("qase")
    elif b == "jira" and "jira" not in out:
        out.append("jira")
    return out


def _mcp_step_default_open(mcp_conn: str, real_name: str = "") -> bool:
    """Expand Jira/Qase MCP steps by default so progress (input/output) is visible like a live log."""
    if not _env_truthy("CHAINLIT_MCP_PROGRESS_STEPS_EXPAND", default=True):
        return False
    return _effective_mcp_display_bucket(mcp_conn, real_name) in ("qase", "jira")


def _openai_tool_spec_function_name(entry: Any) -> str | None:
    """``function.name`` from a Chat Completions tool entry (dict or OpenAI/Pydantic ``Tool``)."""
    if isinstance(entry, dict):
        fn = entry.get("function")
        if isinstance(fn, dict):
            n = fn.get("name")
            return n if isinstance(n, str) else None
        return None
    fn = getattr(entry, "function", None)
    if fn is None:
        return None
    n = getattr(fn, "name", None)
    return n if isinstance(n, str) else None


def _coerce_tool_spec_to_dict(entry: Any) -> dict[str, Any] | None:
    """Ensure tool list entries are plain dicts (OpenAI SDK may use Pydantic ``Tool`` models)."""
    if isinstance(entry, dict) and isinstance(entry.get("function"), dict):
        return entry
    fn = getattr(entry, "function", None)
    if fn is None:
        return None
    name = getattr(fn, "name", None)
    if not isinstance(name, str) or not name.strip():
        return None
    desc = getattr(fn, "description", None) or ""
    params = getattr(fn, "parameters", None)
    if params is not None and not isinstance(params, dict):
        dump = getattr(params, "model_dump", None)
        if callable(dump):
            try:
                params = dump(exclude_none=True)
            except Exception:
                params = None
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
    if not isinstance(params, dict):
        params = {"type": "object", "properties": {}}
    desc_max = _openai_function_description_max()
    ds = desc[:desc_max] if isinstance(desc, str) else str(desc)[:desc_max]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": ds,
            "parameters": params,
        },
    }


def _normalize_tool_specs_dicts(tool_specs: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tool_specs:
        d = _coerce_tool_spec_to_dict(t)
        if d:
            out.append(d)
    return out


def _tools_without_qase_connections(
    tool_specs: list[Any],
    routing: dict[str, tuple[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]], str | None]:
    """Remove tools from connections whose name looks like Qase. Returns (_, _, 'only_qase') if nothing left."""
    specs = _normalize_tool_specs_dicts(tool_specs)
    kept_oai = {oai for oai, (mcp, op) in routing.items() if not _mcp_connection_or_op_is_qase(mcp, op)}
    if len(kept_oai) == len(routing):
        return specs, routing, None
    if not kept_oai:
        return [], {}, "only_qase"
    new_routing = {k: v for k, v in routing.items() if k in kept_oai}
    new_specs = [t for t in specs if _openai_tool_spec_function_name(t) in kept_oai]
    return new_specs, new_routing, None


def _sanitize_oai_tool_function_name(name: str) -> str:
    """Chat Completions ``function.name`` must match ``^[a-zA-Z0-9_-]+$`` (and length limits)."""
    if not isinstance(name, str):
        return "tool"
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip())
    if len(s) > 64:
        s = s[:64]
    return s if s else "tool"


def _sanitize_assistant_tool_calls_in_messages(messages: list[dict[str, Any]]) -> None:
    """Strip/replace characters OpenAI rejects in historic ``assistant.tool_calls`` turns."""
    for m in messages:
        if m.get("role") != "assistant":
            continue
        tcs = m.get("tool_calls")
        if not isinstance(tcs, list):
            continue
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function")
            if not isinstance(fn, dict):
                continue
            raw = fn.get("name")
            fn["name"] = _sanitize_oai_tool_function_name(raw if isinstance(raw, str) else "")


def _sanitize_tool_choice_function_name(tool_choice: Any) -> None:
    if not isinstance(tool_choice, dict):
        return
    if tool_choice.get("type") != "function":
        return
    fn = tool_choice.get("function")
    if not isinstance(fn, dict):
        return
    raw = fn.get("name")
    if isinstance(raw, str):
        fn["name"] = _sanitize_oai_tool_function_name(raw)


def _resolve_tool_call_to_routing_table(
    fn_raw: str,
    routing: dict[str, tuple[str, str]],
    routing_complete: dict[str, tuple[str, str]],
) -> tuple[str | None, dict[str, tuple[str, str]] | None]:
    """Map a model tool name to a routing dict entry. Tries live ``routing`` then a snapshot (e.g. after
    ``getJiraIssue`` was removed from the active tool list).
    """
    fn_san = _sanitize_oai_tool_function_name(fn_raw)
    for tbl in (routing, routing_complete):
        k = _resolve_mcp_tool_routing_key(fn_raw, tbl) or _resolve_mcp_tool_routing_key(fn_san, tbl)
        if k and k in tbl:
            return k, tbl
    if fn_san in routing:
        return fn_san, routing
    if fn_san in routing_complete:
        return fn_san, routing_complete
    return None, None


def _safe_oai_tool_name(mcp_name: str, tool_name: str, suffix: int) -> str:
    """OpenAI function names: ^[a-zA-Z0-9_-]{1,64}$."""
    raw = f"{mcp_name}__{tool_name}"
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
    if len(cleaned) > 64:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", f"m{suffix}_{tool_name}")[:64]
    return _sanitize_oai_tool_function_name(cleaned)


def _tool_result_to_text(result: CallToolResult) -> str:
    parts: list[str] = []
    if result.isError:
        parts.append("(MCP operation reported isError)")
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        else:
            parts.append(block.model_dump_json(exclude_none=True))
    if result.structuredContent:
        parts.append(json.dumps(result.structuredContent, indent=2, default=str))
    return "\n\n".join(parts) if parts else "(empty tool result)"


def _mcp_schema_has_only_optional_args(tool: Any) -> bool:
    sch = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
    return not (sch.get("required") or [])


def _pick_mcp_probe_tool(mcp_conn: str, tools: list[Any]) -> tuple[str, dict[str, Any]] | None:
    """One lightweight ``call_tool`` per server: Qase ``list_projects``, GitHub ``get_me``, Atlassian user/resource, Playwright ``browser_tabs``."""
    if not tools:
        return None
    names = {t.name for t in tools}
    conn_l = mcp_conn.lower()

    is_qase = _mcp_name_looks_like_qase(mcp_conn) or any(_is_qase_mcp_operation(t.name) for t in tools)
    is_pw = "playwright" in conn_l or any(str(t.name).startswith("browser_") for t in tools)
    is_gh = "github" in conn_l
    is_jira = (
        _mcp_ui_bucket(mcp_conn) == "jira"
        or "atlassian" in conn_l
        or "jira" in conn_l
        or "rovo" in conn_l
        or any(
            t.name in ("atlassianUserInfo", "getAccessibleAtlassianResources", "getJiraIssue")
            for t in tools
        )
    )

    if is_qase and "list_projects" in names:
        return "list_projects", {"limit": 5}
    if is_pw and "browser_tabs" in names:
        return "browser_tabs", {"action": "list"}
    if is_gh and "get_me" in names:
        return "get_me", {}
    if is_jira:
        for cand in ("atlassianUserInfo", "getAccessibleAtlassianResources"):
            if cand in names and _mcp_schema_has_only_optional_args(next(t for t in tools if t.name == cand)):
                return cand, {}

    unsafe = (
        "delete_",
        "create_",
        "update_",
        "edit",
        "add_",
        "remove_",
        "merge_",
        "push_",
        "browser_navigate",
        "browser_click",
    )

    def _safe_fallback(t: Any) -> bool:
        n = str(t.name).lower()
        if any(n.startswith(p) for p in unsafe):
            return False
        return _mcp_schema_has_only_optional_args(t) and (
            n.startswith(("get", "list", "search")) or str(t.name) in ("atlassianUserInfo", "getAccessibleAtlassianResources")
        )

    for t in sorted(tools, key=lambda x: x.name):
        if _safe_fallback(t):
            return t.name, {}
    return None


async def _run_mcp_connectivity_probe(ws: WebsocketSession) -> str:
    """``list_tools`` then exactly one ``call_tool`` per MCP connection; results in Chainlit Steps + summary."""
    list_timeout = float(os.getenv("CHAINLIT_MCP_LIST_TOOLS_TIMEOUT", "45"))
    call_timeout = int(os.getenv("CHAINLIT_MCP_CALL_TOOL_TIMEOUT", "90"))
    preview_max = int(os.getenv("CHAINLIT_MCP_PROBE_OUTPUT_MAX", "2400"))
    lines: list[str] = [
        "## MCP setup probe",
        "",
        "Each connection: **one** `call_tool` using a minimal read-only operation (after resolving names via `list_tools`).",
        "",
    ]
    if not ws.mcp_sessions:
        return "## MCP setup probe\n\nNo MCP connections — use the plug menu to add servers."

    for mcp_conn, mcp_wrap in ws.mcp_sessions.items():
        async with cl.Step(
            name=f"MCP probe · {mcp_conn}",
            type="run",
            tags=["mcp-probe", "setup"],
            default_open=True,
        ) as step:
            step.input = {"connection": mcp_conn}
            try:
                listed = await asyncio.wait_for(
                    mcp_wrap.client.list_tools(),
                    timeout=list_timeout,
                )
                tlist = list(listed.tools)
            except Exception as e:
                out = f"`list_tools` failed: {e!s}"
                step.output = out
                lines.append(f"- **{mcp_conn}**: **list_tools** failed — `{e!s}`")
                continue

            picked = _pick_mcp_probe_tool(mcp_conn, tlist)
            if not picked:
                out = f"Connected (**{len(tlist)}** tools). No safe one-call probe selected (add a read-only tool with no required args, or rename connection to include qase/github/playwright/atlassian)."
                step.output = out
                lines.append(f"- **{mcp_conn}**: connected (**{len(tlist)}** tools); **no probe**.")
                continue

            op, args = picked
            step.input = {"connection": mcp_conn, "operation": op, "arguments": args}
            try:
                result = await mcp_wrap.client.call_tool(
                    op,
                    arguments=args,
                    read_timeout_seconds=timedelta(seconds=call_timeout),
                )
                txt = _tool_result_to_text(result)
                err = bool(result.isError)
                preview = txt if len(txt) <= preview_max else txt[:preview_max] + "…"
                step.output = f"**`{op}`** arguments: `{args}`\n\n{preview}"
                status = "error" if err else "ok"
                lines.append(
                    f"- **{mcp_conn}**: **`{op}`** → **{status}** ({len(txt)} chars)"
                    + (" (see step output)" if len(txt) > preview_max else "")
                )
            except Exception as e:
                step.output = f"`{op}` raised: {e!s}"
                lines.append(f"- **{mcp_conn}**: **`{op}`** failed — `{e!s}`")

    lines.append("")
    lines.append("Send **`/mcp-setup`** again after reconnecting servers. This path does **not** call OpenAI.")
    return "\n".join(lines)


def _is_mcp_connectivity_checklist_only(text: str) -> bool:
    """Heuristic: user pasted a Setup starter about MCP env (not a follow-up about errors)."""
    if not _env_truthy("CHAINLIT_MCP_CHECKLIST_AUTO_PROBE", default=True):
        return False
    t = text.strip()
    if len(t) > 3600 or len(t) < 80:
        return False
    low = re.sub(r"[*_`]+", "", t.lower())
    for dash in ("\u2014", "\u2013", "—", "–"):
        low = low.replace(dash, "-")
    if "not found" in low or ("error" in low and "why" in low):
        return False
    # Current Setup starter: «MCP plug + Playwright env»
    if low.startswith("setup - mcp:"):
        if not all(n in low for n in ("plug", "playwright")):
            return False
        if "jira" not in low and "atlassian" not in low:
            return False
        return True
    # Legacy long paste from older builds
    if not (
        low.startswith("confirm atlassian")
        or low.startswith("quick connectivity")
    ):
        return False
    needles = ("jira", "qase", "playwright", "plug", "mcp-setup")
    if not all(n in low for n in needles):
        return False
    return "/mcp-setup" in low or "run /mcp-setup" in low


def _message_triggers_local_mcp_probe(user_text: str) -> bool:
    """Run the built-in probe without OpenAI: slash command, its own line, or checklist-only paste."""
    s = user_text.strip().lower()
    if s in ("/mcp-setup", "/mcp-test", "/mcp-probe"):
        return True
    for line in user_text.splitlines():
        if line.strip().lower() in ("/mcp-setup", "/mcp-test", "/mcp-probe"):
            return True
    return _is_mcp_connectivity_checklist_only(user_text)


def _try_parse_json_loose(s: str) -> Any | None:
    """Parse JSON from MCP text (handles trailing noise)."""
    s = s.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        i = s.find("{")
        if i < 0:
            return None
        for j in range(len(s), i + 2, -1):
            try:
                return json.loads(s[i:j])
            except json.JSONDecodeError:
                continue
        return None


def _adf_to_plain(node: Any, max_chars: int) -> str:
    """Best-effort Atlassian Document Format → plain text."""
    if max_chars <= 0:
        return ""
    if isinstance(node, str):
        return node[:max_chars]
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            return node["text"][:max_chars]
        acc: list[str] = []
        for child in node.get("content") or []:
            if len("".join(acc)) >= max_chars:
                break
            acc.append(_adf_to_plain(child, max_chars - len("".join(acc))))
        return " ".join(acc).strip()[:max_chars]
    if isinstance(node, list):
        return " ".join(_adf_to_plain(x, max_chars // max(len(node), 1)) for x in node[:50])[:max_chars]
    return str(node)[:max_chars]


def _preview_jira_field(val: Any, max_chars: int) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()[:max_chars]
    if isinstance(val, dict):
        if val.get("type") == "doc" or "content" in val:
            return _adf_to_plain(val, max_chars)
        if isinstance(val.get("name"), str):
            return val["name"][:max_chars]
        return json.dumps(val, default=str)[:max_chars]
    if isinstance(val, list):
        return json.dumps(val, default=str)[:max_chars]
    return str(val)[:max_chars]


def _jira_issue_compact_header(text: str) -> str | None:
    """Pull key, summary, description preview from Jira-style JSON so truncation does not hide them."""
    data = _try_parse_json_loose(text)
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("issue"), dict):
        data = data["issue"]
    inner = data.get("data")
    if isinstance(inner, dict) and "fields" in inner:
        data = inner
    fields = data.get("fields")
    if not isinstance(fields, dict):
        return None
    key = data.get("key") or fields.get("key") or ""
    summary = _preview_jira_field(fields.get("summary"), 4000)
    desc = fields.get("description")
    desc_s = _preview_jira_field(desc, 8000)
    rend = fields.get("renderedFields")
    if isinstance(rend, dict) and not desc_s:
        desc_s = _preview_jira_field(rend.get("description"), 8000)
    st = fields.get("status")
    status_name = st.get("name") if isinstance(st, dict) else (str(st) if st is not None else "")
    pri = fields.get("priority")
    pri_name = pri.get("name") if isinstance(pri, dict) else (str(pri) if pri is not None else "")
    assignee = fields.get("assignee")
    if isinstance(assignee, dict):
        an = assignee.get("displayName") or assignee.get("name") or ""
    else:
        an = str(assignee or "")
    lines = [
        "--- Jira issue (key fields from MCP JSON) ---",
        f"Key: {key}",
        f"Summary: {summary if summary else '(empty or null in payload)'}",
        f"Status: {status_name}",
        f"Priority: {pri_name}",
        f"Assignee: {an}",
        "",
        "Description (preview):",
        desc_s if desc_s else "(empty or null in payload — check raw JSON below if truncated)",
    ]
    return "\n".join(lines)


def _maybe_jira_compact_truncate(text: str, max_chars: int) -> str:
    """If JSON looks like a Jira issue, prepend key fields so the model still sees summary/description."""
    if len(text) <= max_chars:
        return text
    if os.getenv("CHAINLIT_JIRA_ISSUE_SMART_TRUNCATE", "1").lower() in ("0", "false", "no"):
        return text[:max_chars] + "\n\n[…truncated…]"
    compact = _jira_issue_compact_header(text)
    if not compact:
        return text[:max_chars] + "\n\n[…truncated…]"
    sep = "\n\n--- MCP JSON (truncated) ---\n"
    room = max_chars - len(compact) - len(sep) - 40
    if room >= 400:
        return compact + sep + text[:room] + "\n\n[…truncated for model context…]"
    if len(compact) + len(sep) + 120 <= max_chars:
        tail_room = max(80, max_chars - len(compact) - len(sep) - 10)
        return compact + sep + text[:tail_room] + "\n…"
    if len(compact) <= max_chars - 40:
        return compact + "\n\n[…raw JSON omitted in this slot: increase CHAINLIT_MCP_TOOL_LEGACY_MAX_CHARS…]"
    return compact[: max_chars - 80] + "\n\n[…truncated…]"


def _openai_chat_completions_tools_cap() -> int:
    """Maximum ``tools`` array length for Chat Completions.

    OpenAI returns ``400 invalid_request_error`` (e.g. ``array_above_max_length``) if this is exceeded.
    """
    try:
        v = int(os.getenv("CHAINLIT_OPENAI_MAX_TOOLS", "128"))
    except ValueError:
        v = 128
    # api.openai.com currently enforces 128; keep env knob for lower caps or future API changes.
    return max(1, min(v, 128))


def _effective_mcp_max_tools(user_text: str) -> int:
    """Fewer tools in full-workflow mode to shrink the ``functions`` payload (~9k tokens with 50+ tools)."""
    base = int(os.getenv("CHAINLIT_MCP_MAX_TOOLS", "35"))
    if _pipeline_keywords(user_text):
        base = int(os.getenv("CHAINLIT_MCP_MAX_TOOLS_WORKFLOW", "28"))
    cap = _openai_chat_completions_tools_cap()
    return max(5, min(base, cap))


def _mcp_limits(user_text: str | None = None) -> tuple[int, float]:
    """Max MCP operations mirrored into the OpenAI request, list_tools timeout seconds."""
    list_timeout = float(os.getenv("CHAINLIT_MCP_LIST_TOOLS_TIMEOUT", "45"))
    cap = _openai_chat_completions_tools_cap()
    if user_text is not None:
        max_tools = _effective_mcp_max_tools(user_text)
    else:
        max_tools = int(os.getenv("CHAINLIT_MCP_MAX_TOOLS", "35"))
    return max(5, min(max_tools, cap)), list_timeout


# MCP operation names that are rarely needed for requirement / gap analysis and often waste tokens (huge payloads).
_DEFAULT_MINIMAL_JIRA_TOOL_DENY = frozenset({"getVisibleJiraProjects"})

# When the user message looks like a Jira issue key, non-Qase tools are sorted alphabetically by default.
# With Qase reservation + a low CHAINLIT_MCP_MAX_TOOLS(_WORKFLOW) cap, that can omit **getJiraIssue**
# (many add*/create*/getConfluence* names sort earlier). These names are added first among non-Qase tools.
_JIRA_ISSUE_KEY_PRIORITY_TOOLS: tuple[str, ...] = (
    "getJiraIssue",
    "searchJiraIssuesUsingJql",
    "addCommentToJiraIssue",
    "getAccessibleAtlassianResources",
    "getJiraIssueRemoteIssueLinks",
    "getTransitionsForJiraIssue",
)


def _should_use_minimal_jira_toolset(user_text: str) -> bool:
    """Hide noisy Jira discovery tools when the user is doing targeted analysis, not a full multi-stage run."""
    v = os.getenv("CHAINLIT_MCP_JIRA_MINIMAL", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    # auto (default): minimal unless the user asked for the full pipeline
    if _pipeline_keywords(user_text):
        return False
    if _looks_like_jira_issue_key(user_text):
        return True
    t = user_text.lower()
    return any(
        k in t
        for k in (
            "requirement analysis",
            "gap analysis",
            "gap score",
            "test readiness",
            "analyze the issue",
            "planner output",
        )
    )


def _denied_mcp_tool_names(user_text: str) -> set[str]:
    """Exact MCP tool names to omit from the OpenAI tool list (still available if you disable filters)."""
    denied: set[str] = {x.strip() for x in os.getenv("CHAINLIT_MCP_TOOL_DENYLIST", "").split(",") if x.strip()}
    # PROJ-123 is a Jira key, not Bitbucket workspace/repo — models often mis-call Bitbucket for GPS-7525-style keys.
    if _env_truthy("CHAINLIT_MCP_AUTO_DENY_BITBUCKET_FOR_JIRA_KEY", default=True):
        if _looks_like_jira_issue_key(user_text):
            denied |= {
                "bitbucketRepository",
                "bitbucketDeployment",
            }
    # "Fetch PROJ-123" is read-only — models mispick editJiraIssue, atlassianUserInfo, or Confluence comment APIs (PROJ-123 is not a commentId).
    if _env_truthy("CHAINLIT_MCP_DENY_EDIT_AND_USERINFO_ON_FETCH", default=True):
        if _heuristic_require_jira_fetch_tools(user_text, ""):
            denied |= {
                "editJiraIssue",
                "atlassianUserInfo",
                "getConfluenceCommentChildren",
                "addWorklogToJiraIssue",
            }
    # With cloud id in .env, discovery is redundant — models loop on getAccessibleAtlassianResources instead of getJiraIssue.
    if _env_truthy("CHAINLIT_MCP_SKIP_GET_ACCESSIBLE_WHEN_CLOUD_ID", default=True):
        if _heuristic_require_jira_fetch_tools(user_text, "") and _jira_cloud_id_from_env():
            denied |= {"getAccessibleAtlassianResources"}
    # "Run workflow" / full pipeline — not a place for worklogs or identity pings; use getJiraIssue + planner path.
    if _env_truthy("CHAINLIT_MCP_DENY_SPAM_TOOLS_ON_WORKFLOW", default=True):
        if _pipeline_keywords(user_text):
            denied |= {
                "atlassianUserInfo",
                "addWorklogToJiraIssue",
            }
    if _should_use_minimal_jira_toolset(user_text):
        denied |= set(_DEFAULT_MINIMAL_JIRA_TOOL_DENY)
    return denied


def _mcp_tool_excluded_by_policy(
    mcp_tool_name: str,
    denied_names: set[str],
    user_text: str,
    mcp_connection: str = "",
) -> bool:
    """Apply denylist with case-insensitive match + broad Bitbucket/Confluence rules (MCP names vary by server)."""
    if not mcp_tool_name:
        return True
    n_low = mcp_tool_name.lower()
    if mcp_tool_name in denied_names:
        return True
    lowered = {d.lower() for d in denied_names}
    if n_low in lowered:
        return True
    # Any Bitbucket* tool when a Jira key is present (models invent workspace/repo; not just Repository/Deployment).
    if _env_truthy("CHAINLIT_MCP_AUTO_DENY_BITBUCKET_FOR_JIRA_KEY", default=True):
        if _looks_like_jira_issue_key(user_text) and n_low.startswith("bitbucket"):
            return True
    # Confluence tools on "Fetch PROJ-123" — Jira keys are not page/comment ids.
    if _env_truthy("CHAINLIT_MCP_FETCH_BLOCK_CONFLUENCE_TOOLS", default=True):
        if _heuristic_require_jira_fetch_tools(user_text, "") and (
            "confluence" in n_low or n_low.startswith("getconfluence")
        ):
            return True
    # Qase MCP: omit destructive delete_* ops from the model tool list (reduces accidents / permission errors).
    if _env_truthy("CHAINLIT_MCP_QASE_EXCLUDE_DELETE_TOOLS", default=True):
        if n_low.startswith("delete_") and _is_qase_mcp_operation(mcp_tool_name):
            return True
    return False


def _openai_function_description_max() -> int:
    """Keep the ``tools`` payload small; MCP still exposes full behavior at call time."""
    return max(128, int(os.getenv("CHAINLIT_OPENAI_FUNCTION_DESC_MAX", "512")))


def _effective_tool_result_max_chars(user_text: str) -> int:
    """Per tool message cap; workflow mode uses a smaller default so many rounds fit in 128k tokens."""
    if _pipeline_keywords(user_text):
        return max(2000, int(os.getenv("CHAINLIT_MCP_TOOL_RESULT_MAX_CHARS_WORKFLOW", "8000")))
    return max(2000, int(os.getenv("CHAINLIT_MCP_TOOL_RESULT_MAX_CHARS", "12000")))


def _truncate_tool_text_for_model(text: str, user_text: str) -> str:
    cap = _effective_tool_result_max_chars(user_text)
    if len(text) <= cap:
        return text
    if '"fields"' in text and ("summary" in text.lower() or '"key"' in text):
        return _maybe_jira_compact_truncate(text, cap)
    return (
        text[:cap]
        + "\n\n[…truncated for model context; "
        f"max {cap} chars — set CHAINLIT_MCP_TOOL_RESULT_MAX_CHARS / _WORKFLOW; full text is in the Chainlit step …]"
    )


def _cap_system_prompt_if_needed(messages: list[dict[str, Any]], user_text: str) -> None:
    if not messages or messages[0].get("role") != "system":
        return
    c = messages[0].get("content", "")
    if not isinstance(c, str):
        return
    max_sys = int(os.getenv("CHAINLIT_SYSTEM_PROMPT_MAX_CHARS", "48000"))
    if _pipeline_keywords(user_text):
        max_sys = int(os.getenv("CHAINLIT_SYSTEM_PROMPT_MAX_CHARS_WORKFLOW", "26000"))
    if len(c) > max_sys:
        messages[0]["content"] = (
            c[:max_sys]
            + "\n\n[…system prompt truncated… use CHAINLIT_SKILLS_MAX_CHARS_WORKFLOW / CHAINLIT_SKILL_PROFILE=orchestrator …]"
        )


def _compact_messages_for_openai(messages: list[dict[str, Any]], user_text: str) -> None:
    """Shrink older tool outputs: multi-round Jira workflows otherwise exceed 128k context."""
    max_full = _effective_tool_result_max_chars(user_text)
    legacy = max(400, int(os.getenv("CHAINLIT_MCP_TOOL_LEGACY_MAX_CHARS", "1800")))
    keep_last = max(1, int(os.getenv("CHAINLIT_MCP_TOOL_RESULT_KEEP_LAST", "6")))

    tool_idxs = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for j, ti in enumerate(tool_idxs):
        m = messages[ti]
        c = m.get("content", "")
        if not isinstance(c, str):
            continue
        if j >= len(tool_idxs) - keep_last:
            if len(c) > max_full:
                m["content"] = (
                    _maybe_jira_compact_truncate(c, max_full)
                    if '"fields"' in c
                    else c[:max_full] + "\n\n[…truncated…]"
                )
        elif len(c) > legacy:
            m["content"] = (
                _maybe_jira_compact_truncate(c, legacy)
                if '"fields"' in c
                else (
                    c[:legacy]
                    + "\n\n[…older MCP output truncated; rely on recent tool messages above …]"
                )
            )


def _mcp_read_cache_key(mcp_conn: str, real_name: str, args: dict[str, Any]) -> str:
    # getJiraIssue: model often varies JSON (extra fields, optional cloudId) — dedupe by issue key only.
    if real_name == "getJiraIssue":
        ik = _issue_key_from_jira_mcp_args(args)
        if ik:
            return f"{mcp_conn}\x1fgetJiraIssue\x1f{ik}"
    # Args rarely matter; duplicate calls waste rounds.
    if real_name == "getAccessibleAtlassianResources":
        return f"{mcp_conn}\x1fgetAccessibleAtlassianResources"
    if real_name == "atlassianUserInfo":
        return f"{mcp_conn}\x1fatlassianUserInfo"
    if real_name == "addCommentToJiraIssue":
        ik = _issue_key_from_jira_mcp_args(args) or str(args.get("issueIdOrKey", "") or "").strip()
        body = _jira_comment_body_from_args(args)
        fp = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:32]
        return f"{mcp_conn}\x1faddCommentToJiraIssue\x1f{ik}\x1f{fp}"
    try:
        return f"{mcp_conn}\x1f{real_name}\x1f{json.dumps(args, sort_keys=True, default=str)}"
    except TypeError:
        return f"{mcp_conn}\x1f{real_name}\x1f{json.dumps(args, default=str)}"


# Idempotent reads: identical args in one chat turn → same result; skip duplicate MCP round-trips.
_MCP_DEDUP_READ_TOOLS = frozenset(
    {
        "getJiraIssue",
        "getAccessibleAtlassianResources",
        "searchJiraIssuesUsingJql",
        "getTransitionsForJiraIssue",
        "getJiraIssueRemoteIssueLinks",
        "atlassianUserInfo",
    }
)
# Same-arg writes repeated in one turn (model spam) — skip duplicate MCP round-trips.
_MCP_DEDUP_WRITE_TOOLS = frozenset(
    {
        "addCommentToJiraIssue",
        # Qase: models often emit duplicate create_suite / create_case (parallel or across MCP rounds).
        "create_suite",
        "create_case",
    }
)
_MCP_DEDUP_IDENTICAL_CALLS_TOOLS = _MCP_DEDUP_READ_TOOLS | _MCP_DEDUP_WRITE_TOOLS

_MCP_SESSION_READ_CACHE_KEY = "chainlit_mcp_read_session_cache"
_MCP_QASE_CREATE_SESSION_CACHE_KEY = "chainlit_mcp_qase_create_session_cache"


def _session_cacheable_mcp_tool(real_name: str) -> bool:
    """Which MCP reads to remember across user messages (same Chainlit session)."""
    if not _env_truthy("CHAINLIT_MCP_SESSION_CACHE_READS", default=True):
        return False
    raw = os.getenv(
        "CHAINLIT_MCP_SESSION_CACHE_TOOLS",
        "getJiraIssue,getAccessibleAtlassianResources,atlassianUserInfo",
    ).strip()
    if not raw or raw.lower() == "all":
        return real_name in _MCP_DEDUP_READ_TOOLS
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    return real_name in allowed


def _session_mcp_read_cache_get(cache_key: str) -> str | None:
    try:
        c = user_session.get(_MCP_SESSION_READ_CACHE_KEY)
        if isinstance(c, dict):
            return c.get(cache_key)
    except Exception:
        pass
    return None


def _session_mcp_read_cache_put(cache_key: str, text: str) -> None:
    if not text or not isinstance(text, str):
        return
    if text.startswith("MCP call_tool error"):
        return
    if "(MCP operation reported isError)" in text[:400]:
        return
    try:
        c = user_session.get(_MCP_SESSION_READ_CACHE_KEY)
        if not isinstance(c, dict):
            c = {}
        c[cache_key] = text
        max_n = max(10, int(os.getenv("CHAINLIT_MCP_SESSION_CACHE_MAX_ENTRIES", "80")))
        while len(c) > max_n:
            c.pop(next(iter(c)))
        user_session.set(_MCP_SESSION_READ_CACHE_KEY, c)
    except Exception:
        pass


def _qase_create_session_cache_key(mcp_conn: str, real_name: str, args: dict[str, Any]) -> str | None:
    """Stable key across duplicate model calls: suite by project+title; case by full payload hash."""
    if real_name == "create_suite":
        code = str(args.get("code") or "").strip().upper()
        title = " ".join(str(args.get("title") or "").split())
        if not code or not title:
            return None
        return f"{mcp_conn}\x1fcreate_suite\x1f{code}\x1f{title}"
    if real_name == "create_case":
        try:
            payload = json.dumps(args, sort_keys=True, default=str)
        except TypeError:
            payload = json.dumps(args, default=str)
        digest = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:48]
        return f"{mcp_conn}\x1fcreate_case\x1f{digest}"
    return None


def _session_qase_create_cache_get(key: str) -> str | None:
    try:
        c = user_session.get(_MCP_QASE_CREATE_SESSION_CACHE_KEY)
        if isinstance(c, dict):
            return c.get(key)
    except Exception:
        pass
    return None


def _session_qase_create_cache_put(key: str, text: str) -> None:
    if not text or not isinstance(text, str):
        return
    if text.startswith("MCP call_tool error"):
        return
    if "(MCP operation reported isError)" in text[:400]:
        return
    try:
        c = user_session.get(_MCP_QASE_CREATE_SESSION_CACHE_KEY)
        if not isinstance(c, dict):
            c = {}
        c[key] = text
        max_n = max(10, int(os.getenv("CHAINLIT_MCP_SESSION_CACHE_MAX_ENTRIES", "80")))
        while len(c) > max_n:
            c.pop(next(iter(c)))
        user_session.set(_MCP_QASE_CREATE_SESSION_CACHE_KEY, c)
    except Exception:
        pass


def _should_cache_mcp_tool_result(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    if text.startswith("MCP call_tool error"):
        return False
    return "(MCP operation reported isError)" not in text[:500]


def _normalize_openai_tools_for_chat_api(tool_specs: list[Any]) -> list[dict[str, Any]]:
    """Build Chat Completions ``tools`` entries with a guaranteed shape.

    The OpenAI Python SDK ``maybe_transform`` can pass through dicts that only contain a nested
    ``function`` object and **omit** top-level ``type: function``, which the API rejects with
    ``Missing required parameter: 'tools[0].type'``. Rebuilding from scratch avoids that class of bug.
    """
    out: list[dict[str, Any]] = []
    desc_max = _openai_function_description_max()
    for raw in tool_specs:
        entry: Any = raw if isinstance(raw, dict) else _coerce_tool_spec_to_dict(raw)
        if not isinstance(entry, dict):
            continue
        fn = entry.get("function")
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        params = fn.get("parameters")
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        desc = fn.get("description") or ""
        desc_s = desc[:desc_max] if isinstance(desc, str) else str(desc)[:desc_max]
        entry: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": _sanitize_oai_tool_function_name(name),
                "description": desc_s,
                "parameters": params,
            },
        }
        if fn.get("strict") is True:
            entry["function"]["strict"] = True
        out.append(entry)
    return out


async def _build_openai_tools_and_routing(
    ws: WebsocketSession,
    user_text: str,
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Build OpenAI ``tools`` payload (API shape only) + map function name -> (MCP connection, MCP operation name).

    When the thread looks like a full pipeline or Qase work, **reserve** slots for Qase MCP tools first.
    Otherwise Atlassian/Rovo alone can fill ``CHAINLIT_MCP_MAX_TOOLS`` and the model never sees ``create_case`` / etc.
    """
    max_tools, list_timeout = _mcp_limits(user_text)
    denied_names = _denied_mcp_tool_names(user_text)
    desc_max = _openai_function_description_max()
    tools: list[dict[str, Any]] = []
    routing: dict[str, tuple[str, str]] = {}
    used_names: set[str] = set()
    n = 0

    listed_by_conn: dict[str, list[Any]] = {}
    mcp_items = list(ws.mcp_sessions.items())

    async def _list_tools_one(mcp_name: str, mcp_wrap: Any) -> tuple[str, list[Any]]:
        try:
            listed = await asyncio.wait_for(
                mcp_wrap.client.list_tools(),
                timeout=list_timeout,
            )
            return mcp_name, list(listed.tools)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"list_tools() timed out after {list_timeout}s for MCP {mcp_name!r}. "
                "Check the MCP process or increase CHAINLIT_MCP_LIST_TOOLS_TIMEOUT."
            ) from None

    if mcp_items:
        results = await asyncio.gather(
            *(_list_tools_one(n, w) for n, w in mcp_items),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, BaseException):
                raise r
            mcp_name, tools = r
            listed_by_conn[mcp_name] = tools

    qase_pairs: list[tuple[str, Any]] = []
    other_pairs: list[tuple[str, Any]] = []
    for mcp_name, mcp_tools in listed_by_conn.items():
        for t in mcp_tools:
            if _mcp_tool_excluded_by_policy(t.name, denied_names, user_text, mcp_name):
                continue
            if _mcp_connection_or_op_is_qase(mcp_name, t.name):
                qase_pairs.append((mcp_name, t))
            else:
                other_pairs.append((mcp_name, t))
    def _qase_tool_priority(name: str) -> tuple[int, str]:
        """Prefer write/list tools so reserved slots are not only obscure getters."""
        n = name.lower()
        if any(n.startswith(p) for p in ("create_", "update_", "add_")):
            return (0, name)
        if any(n.startswith(p) for p in ("list_", "get_", "search_")):
            return (1, name)
        return (2, name)

    qase_pairs.sort(key=lambda x: (_qase_tool_priority(x[1].name), x[1].name, x[0]))

    def _other_tool_pair_sort_key(pair: tuple[str, Any]) -> tuple[int | str, ...]:
        mcp_name, t = pair
        name = t.name
        if _looks_like_jira_issue_key(user_text) and name in _JIRA_ISSUE_KEY_PRIORITY_TOOLS:
            return (0, _JIRA_ISSUE_KEY_PRIORITY_TOOLS.index(name), name, mcp_name)
        return (1, name, mcp_name)

    other_pairs.sort(key=_other_tool_pair_sort_key)

    def try_add(mcp_name: str, t: Any) -> None:
        nonlocal n
        if len(tools) >= max_tools:
            return
        oai_name = _safe_oai_tool_name(mcp_name, t.name, n)
        while oai_name in used_names:
            n += 1
            oai_name = _safe_oai_tool_name(mcp_name, t.name, n)
        used_names.add(oai_name)
        routing[oai_name] = (mcp_name, t.name)
        schema = t.inputSchema if isinstance(t.inputSchema, dict) else {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": oai_name,
                    "description": (t.description or "")[:desc_max],
                    "parameters": schema,
                },
            }
        )
        n += 1

    prio_qase = _should_keep_qase_tools_with_jira_thread(user_text) and bool(qase_pairs)
    qase_reserve = max(0, min(int(os.getenv("CHAINLIT_MCP_QASE_TOOL_RESERVE", "14")), max_tools))

    if prio_qase:
        for mcp_name, t in qase_pairs[:qase_reserve]:
            if len(tools) >= max_tools:
                break
            try_add(mcp_name, t)
        for mcp_name, t in other_pairs:
            if len(tools) >= max_tools:
                break
            try_add(mcp_name, t)
        for mcp_name, t in qase_pairs[qase_reserve:]:
            if len(tools) >= max_tools:
                break
            try_add(mcp_name, t)
    else:
        for mcp_name, t in other_pairs:
            if len(tools) >= max_tools:
                break
            try_add(mcp_name, t)
        for mcp_name, t in qase_pairs:
            if len(tools) >= max_tools:
                break
            try_add(mcp_name, t)

    return tools, routing


_CHAINLIT_MCP_PLACEHOLDER = "__chainlit__"
_CHAINLIT_ASK_USER_OP = "ask_user"


def _chainlit_ask_user_tool_function(desc_max: int, name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                "Pause and ask the human a question in the Chainlit chat UI; wait for a typed reply before continuing. "
                "Use for clarifications, approvals, or choices that MCP cannot supply. Prefer MCP tools for Jira/Qase data."
            )[:desc_max],
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Question or prompt shown to the user (markdown allowed).",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Seconds to wait for an answer (30–3600). Default from CHAINLIT_ASK_USER_TIMEOUT.",
                    },
                },
                "required": ["question"],
            },
        },
    }


def _maybe_append_chainlit_ask_user_tool(
    tool_specs: list[Any],
    routing: dict[str, tuple[str, str]],
    max_tools: int,
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Inject a non-MCP tool that runs ``AskUserMessage`` (human-in-the-loop)."""
    if not _env_truthy("CHAINLIT_ASK_USER_TOOL", default=False):
        return _normalize_tool_specs_dicts(tool_specs), routing
    raw_name = (os.getenv("CHAINLIT_ASK_USER_TOOL_NAME") or "chainlit_ask_user").strip()
    if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", raw_name):
        raw_name = "chainlit_ask_user"
    specs = _normalize_tool_specs_dicts(tool_specs)
    if any(_openai_tool_spec_function_name(t) == raw_name for t in specs):
        return specs, routing
    out_specs = list(specs)
    if len(out_specs) >= max_tools:
        if not _env_truthy("CHAINLIT_ASK_USER_TOOL_FORCE", default=False):
            return specs, routing
        out_specs = out_specs[:-1]
    desc_max = _openai_function_description_max()
    out_specs.append(_chainlit_ask_user_tool_function(desc_max, raw_name))
    out_route = dict(routing)
    out_route[raw_name] = (_CHAINLIT_MCP_PLACEHOLDER, _CHAINLIT_ASK_USER_OP)
    return out_specs, out_route


async def _run_chainlit_ask_user(args: dict[str, Any]) -> str:
    """Execute the Chainlit UI prompt; return text for the OpenAI tool role."""
    q = str(args.get("question") or "").strip() or "Please provide input:"
    default_tmo = int(os.getenv("CHAINLIT_ASK_USER_TIMEOUT", "300"))
    try:
        tmo = int(args.get("timeout_seconds") or default_tmo)
    except (TypeError, ValueError):
        tmo = default_tmo
    tmo = max(30, min(tmo, 3600))
    tool_text = ""
    try:
        async with cl.Step(
            name="Human loop · ask user",
            type="run",
            tags=["human-loop", "ask-user"],
        ) as ask_step:
            ask_step.input = {"question": q, "timeout_seconds": tmo}
            res = await cl.AskUserMessage(content=q, timeout=tmo, raise_on_timeout=False).send()
            if res and isinstance(res, dict):
                out = res.get("output")
                if isinstance(out, str) and out.strip():
                    tool_text = f"The user replied:\n{out.strip()}"
                else:
                    tool_text = "(The user sent an empty reply.)"
            else:
                tool_text = (
                    "(Timed out or no reply — you may ask again with chainlit_ask_user or continue with best effort.)"
                )
            ask_step.output = tool_text[: int(os.getenv("CHAINLIT_MCP_STEP_OUTPUT_MAX", "12000"))]
    except Exception as e:
        tool_text = f"(chainlit_ask_user failed: {e!s})"
    return tool_text


async def _run_openai_with_mcp(user_text: str, ws: WebsocketSession) -> str:
    openai_timeout = float(os.getenv("CHAINLIT_OPENAI_TIMEOUT", "120"))
    call_tool_timeout = int(os.getenv("CHAINLIT_MCP_CALL_TOOL_TIMEOUT", "90"))
    thread_h = _heuristic_thread_text(user_text)
    # Prior chat rows may omit the current line — always merge so PROJ-123 in this message is detected.
    jira_detect_blob = f"{thread_h}\n{user_text}".strip()
    openai_setup_only = _is_openai_setup_starter_message(user_text)
    max_rounds = _effective_mcp_max_rounds(jira_detect_blob)
    if openai_setup_only:
        max_rounds = 1
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return (
            "No OPENAI_API_KEY in the environment. Add it to `.env` and restart Chainlit. "
            "The model uses the API to decide which **MCP** operations to run; execution is always via MCP `call_tool`."
        )

    if not ws.mcp_sessions and not openai_setup_only:
        return "No MCP servers connected. Use the plug icon → add your Atlassian / Qase connections, then ask again."

    model = (_session_openai_model() or "gpt-4.1").strip()
    client = _create_openai_client(openai_timeout)

    probe_err = await _probe_openai_reachable(client)
    if probe_err:
        return (
            "OpenAI API is not reachable (quick probe failed):\n\n"
            f"{probe_err}\n\n"
            "Fix TLS/proxy first, then retry. Tips:\n"
            "- Windows: `pip install truststore` (already listed in requirements) and keep "
            "`CHAINLIT_USE_TRUSTSTORE=1` (default on Windows) so Python uses the OS certificate store.\n"
            "- Or set `CHAINLIT_OPENAI_VERIFY_SSL=0` temporarily to test.\n"
            "- Or set `CHAINLIT_SSL_CA_BUNDLE` to your corporate root CA `.pem`.\n"
            "- Set `HTTPS_PROXY` if required. Skip probe: `CHAINLIT_SKIP_OPENAI_PROBE=1`."
        )

    if openai_setup_only:
        mcp_n = len(ws.mcp_sessions)
        await cl.Message(
            content=(
                "**OpenAI reachable.** **LLM-only check:** The assistant's next reply is **text-only** - "
                "**no MCP tools** are attached, so it cannot call Jira, GitHub, Qase, or Playwright. "
                + (
                    f"({mcp_n} MCP server(s) are connected; they are **not** used for this starter.) "
                    if mcp_n
                    else "(No MCP servers connected - fine for this check.) "
                )
                + "**MCP connectivity:** use the **MCP probe** starter or send **`/mcp-setup`**."
            ),
        ).send()
    else:
        await cl.Message(
            content=(
                "**OpenAI reachable.** Next: load skill context (if enabled), list MCP tools, then call the model "
                "(you will see **Step 2** and **Step 3** when each phase starts)."
            ),
        ).send()

    if _pipeline_keywords(jira_detect_blob):
        await cl.Message(
            content=(
                f"**Full-workflow request:** using up to **{max_rounds}** MCP rounds "
                f"(`CHAINLIT_MCP_MAX_ROUNDS` / `CHAINLIT_MCP_MAX_ROUNDS_WORKFLOW`). "
                "Work stage-by-stage; avoid broad calls (e.g. listing all Jira projects) unless the skill requires it. "
                "**Execute** the next MCP steps (e.g. **getJiraIssue**, Qase) — do **not** spam **atlassianUserInfo**, "
                "**addWorklogToJiraIssue**, or identical **addCommentToJiraIssue**, and do **not** reply with plans-only narration."
            ),
        ).send()

    skill_block, skill_paths = _build_skill_context_for_openai(thread_h, user_text)
    if skill_paths and _env_truthy("CHAINLIT_SKILLS_VERBOSE", default=False):
        listed = ", ".join(f"`{p}`" for p in skill_paths[:25])
        more = f" (+{len(skill_paths) - 25} more)" if len(skill_paths) > 25 else ""
        await cl.Message(content=f"**Skill context:** {listed}{more}").send()

    if openai_setup_only:
        await cl.Message(
            content=(
                "**Step 2/3:** **Skipped** — this starter does **not** load MCP tools into the model request "
                "(prevents accidental Jira/GitHub calls such as **`get_file_contents`** on `.env`, which is often missing "
                "from the remote repo or 404s). **MCP:** use **`/mcp-setup`** or the **MCP plug + Playwright** starter."
            ),
        ).send()
        tool_specs: list[Any] = []
        routing: dict[str, tuple[str, str]] = {}
    else:
        _mt, list_timeout = _mcp_limits(jira_detect_blob)
        n_mcp = len(ws.mcp_sessions)
        await cl.Message(
            content=(
                f"**Step 2/3:** Listing MCP tools from **{n_mcp}** connection(s). "
                f"Requests run **in parallel** (worst case ~{list_timeout:.0f}s if one server is slow). "
                "If this step never finishes, disconnect a stuck MCP in the plug menu or raise `CHAINLIT_MCP_LIST_TOOLS_TIMEOUT`."
            ),
        ).send()

        try:
            tool_specs, routing = await _build_openai_tools_and_routing(ws, jira_detect_blob)
        except RuntimeError as e:
            return str(e)
        if not tool_specs:
            return "Connected MCP servers did not report any callable operations yet. Wait a few seconds and retry, or reconnect."

    if not openai_setup_only and _user_mentions_qase(thread_h) and _routing_has_qase_tools(routing) and not _qase_api_token_in_env():
        return (
            "**Qase MCP needs an API token in the environment.** Add `QASE_API_TOKEN=<your token>` to the project `.env` "
            "(repo root), restart Chainlit, and try again.\n\n"
            "If the token is set but MCP still returns 401, the subprocess may not inherit `.env`: set "
            "`CHAINLIT_MCP_FULL_ENV=1` in `.env` so child processes get the same variables, then restart."
        )

    if not openai_setup_only:
        exclude_qase_for_jira = os.getenv("CHAINLIT_EXCLUDE_QASE_FOR_JIRA_ISSUE_KEY", "1").lower() in (
            "1",
            "true",
            "yes",
        )
        if _looks_like_jira_issue_key(jira_detect_blob) and exclude_qase_for_jira and not _should_keep_qase_tools_with_jira_thread(
            jira_detect_blob
        ):
            tool_specs, routing, qase_problem = _tools_without_qase_connections(tool_specs, routing)
            if qase_problem == "only_qase":
                return (
                    "This request is for a **Jira** issue key, but after applying the MCP operation cap, only the **Qase** "
                    "connection was included (or Atlassian/Rovo is disconnected). Qase cannot fetch Jira issues.\n\n"
                    "Fix: connect **Atlassian / Rovo MCP** in Chainlit (plug icon), e.g. "
                    "`node chainlit-atlassian-mcp.cjs` with `JIRA_EMAIL` and `JIRA_API_TOKEN` in `.env`. "
                    "If both Qase and Atlassian are connected, non-Qase servers are listed first for the cap; "
                    "raise `CHAINLIT_MCP_MAX_TOOLS` only up to `CHAINLIT_OPENAI_MAX_TOOLS` (max 128 for OpenAI)."
                )
            if not tool_specs:
                return (
                    "No MCP operations left for this Jira request after excluding the Qase connection. "
                    "Reconnect Atlassian MCP or set `CHAINLIT_EXCLUDE_QASE_FOR_JIRA_ISSUE_KEY=0` temporarily."
                )

        max_tools, _ = _mcp_limits(jira_detect_blob)
        tool_specs, routing = _maybe_append_chainlit_ask_user_tool(tool_specs, routing, max_tools)
        oai_tool_cap = _openai_chat_completions_tools_cap()
        if len(tool_specs) >= max_tools:
            note = (
                f"\n\n(Only the first {max_tools} MCP operations are mirrored to the model; OpenAI allows at most **{oai_tool_cap}** "
                f"tools per request. Lower `CHAINLIT_MCP_MAX_TOOLS` or disconnect unused MCP servers.)"
            )
        else:
            note = ""
    else:
        note = ""

    if openai_setup_only:
        gap_focus = False
        strip_gji_after_primary = False
        primary_issue_key = ""
        system_body = (
            "You help confirm **Chainlit to OpenAI API** connectivity only.\n\n"
            "**This request has no MCP tools** - do not claim or invent Jira, GitHub, Qase, or Playwright results.\n"
            "Reply in **at most 8 markdown bullets**, using only the user's Setup message and Chainlit status lines in this thread.\n"
            "- If the thread shows **OpenAI reachable** after the ping, this process reached the API with the configured key.\n"
            "- **Step 2 was skipped on purpose** - not an error. Use **`/mcp-setup`** to test MCP servers separately.\n"
            "- Do not tie success or failure to **GitHub `get_file_contents`**, remote `.env`, or MCP calls - none were offered in this path.\n"
        )
    else:
        issue_key_hint = (
            "When fetching **Jira issue data** for a key (e.g. GPS-7525), use **Atlassian/Rovo MCP** "
            "(the **getJiraIssue** operation — use the **exact** tool `name` from this request's **tools** list) — Qase cannot read Jira issues. "
            "**Do not** ask the human for MCP connection names, `Rovo_MCP__…` strings, or to copy tool names from the Chainlit UI. "
            "If **`JIRA_CLOUD_ID`** "
            "is in `.env`, pass the **real UUID string** as **cloudId** in tool JSON — **never** the literal text `{cloudId}` "
            "or other placeholders. Do **not** loop on **getAccessibleAtlassianResources**. Otherwise call "
            "**getAccessibleAtlassianResources** once and reuse that **cloudId**. "
            "Never describe “opening a page”, never suggest the user use a browser for the issue, and never output "
            "placeholder URLs (e.g. **your-jira-instance**.atlassian.net). Answer only from MCP results. "
            "If MCP returns an error or HTML, quote the exact output — do not reinterpret it as a generic "
            "“notifications / page unavailable” story unless that text is literally in the result. "
            "Do **not** say “Unable to fetch summary/description” unless the MCP JSON literally says so; "
            "if `fields.summary` or `fields.description` is null/empty, state that the payload had no text for that field. "
            "**`addCommentToJiraIssue`:** Do **not** spam comments for “progress” or fake Planner steps. "
            "Follow the Planner skill: **getJiraIssue** first, then **one** comment for the **final** gap report when the skill "
            "says to post it — not many comments before analysis. Put interim status in your **chat reply**, not Jira. "
            "**Issue keys vs Bitbucket:** Tokens like **GPS-7525** are **Jira issue keys** (PROJECT + number). "
            "Tokens like **TC-356** are **Qase** test-case style references, **not** Jira — use **Qase MCP** **`get_case`** "
            "(exact tool `name` from this session; pass case id / project / code per schema — often numeric **356**), **not** **getJiraIssue**. "
            "Do **not** treat Jira **PROJ-123** keys as Bitbucket workspace/repo IDs or call **bitbucketRepository** / **bitbucketDeployment**. "
            "To **read** an issue, use **getJiraIssue** only — **not** **editJiraIssue** (that tool updates fields and requires a `fields` object). "
            "**Jira keys are not Confluence ids:** do **not** use **getConfluenceCommentChildren** or other Confluence tools with a PROJ-123 key."
        )
        qase_request_hint = (
            "For **Qase** (test management) projects, cases, suites, plans, or runs, use the **Qase MCP** connection and "
            "answer from MCP output. **Creating** cases/suites requires calling the corresponding Qase MCP operations — "
            "not Jira comments alone. If MCP errors, quote them. If Qase tools are missing from the tool list, say so. "
            "When Qase tools **are** listed and `QASE_API_TOKEN` is configured, **call them** — do **not** repeatedly ask "
            "the user to confirm Qase connectivity, cloud IDs, MCP tool prefixes, or permission to push tests on every turn. "
            "To **read** a test case by id (e.g. **TC-356**), use **`get_case`** — **not** Jira **getJiraIssue**."
        )
        gap_focus = _is_gap_analysis_focus(user_text)
        strip_gji_after_primary = gap_focus and _env_truthy(
            "CHAINLIT_GAP_ANALYSIS_STRIP_GET_JIRA_AFTER_PRIMARY",
            default=True,
        )
        primary_issue_key = _last_jira_key_in_text(jira_detect_blob) or _first_jira_key_in_text(user_text)

        system_body = (
            "You are a helpful assistant. Data access goes through **connected MCP servers** (e.g. Jira, Qase). "
            "Follow the **skills and rules** above for workflow, gates, and output shapes; use MCP for facts; "
            "never guess what you could fetch via MCP."
        )
        _sys_go, _sys_gr = _resolved_github_owner_repo()
        if _sys_go and _sys_gr:
            system_body += (
                f"\n\n**GitHub repo for this Chainlit workspace:** **`{_sys_go}/{_sys_gr}`** "
                f"(from `GITHUB_REPOSITORY` / `ORCHESTRATOR_GITHUB_REPO`, or `git remote origin` on this app). "
                "For **new branches**, **PRs**, **`create_pull_request`**, **`get_file_contents`**, and every GitHub MCP call, "
                f"use **`owner`**=`{_sys_go}` and **`repo`**=`{_sys_gr}` unless the user explicitly names another repository. "
                "README/skills may refer to **“AE.QA.Agentic”** as a product name — that string is **not** always the GitHub "
                "`repo` slug for this checkout. Do **not** assume or output **`surekharapuru123/AE.QA.Agentic`** (or any other "
                "`owner/repo`) from memory or examples when this paragraph gives a different pair."
            )
        if _env_truthy("CHAINLIT_ASK_USER_TOOL", default=False) and any(
            r == _CHAINLIT_ASK_USER_OP for (_m, r) in routing.values()
        ):
            system_body += (
                "\n\n**Human-in-the-loop:** The **chainlit_ask_user** tool is available — use it only for approvals or "
                "clarifications MCP cannot answer. Prefer MCP tools for issue/project data."
            )
        if _chainlit_thread_openai_rows():
            system_body += (
                "\n\n**Conversation thread:** Earlier turns in this chat are included below; reuse Jira issue keys, "
                "summaries, and MCP facts from them — do **not** ask the user to repeat an issue key already stated "
                "above unless they are switching to a different key."
            )
        if _looks_like_jira_issue_key(jira_detect_blob):
            system_body += issue_key_hint
        if (_looks_like_jira_issue_key(jira_detect_blob) or _pipeline_keywords(jira_detect_blob)) and _jira_cloud_id_from_env():
            system_body += _jira_cloud_id_env_prompt_block()
        if _user_mentions_qase(thread_h) or _thread_mentions_qase_stage_work(thread_h):
            system_body += ("\n\n" if _looks_like_jira_issue_key(jira_detect_blob) else "") + qase_request_hint
        if _pipeline_keywords(jira_detect_blob):
            _wf_go, _wf_gr = _resolved_github_owner_repo()
            _pr_url_contract = ""
            if _wf_go and _wf_gr:
                _pr_url_contract = (
                    f"**Stage 3 Automation — `pr_url`:** Must be **`https://github.com/{_wf_go}/{_wf_gr}/pull/<pr_number>`** "
                    f"using GitHub MCP **`owner`**=`{_wf_go}` and **`repo`**=`{_wf_gr}` (this Chainlit checkout / `.env`). "
                    "Do **not** emit example URLs for a different repository.\n"
                )
            system_body += (
                "\n\n**Full workflow:** Advance through orchestrator stages in order. "
                "Use only MCP operations that the current stage needs; do **not** call broad discovery APIs "
                "(e.g. listing every project) unless a skill step explicitly requires it.\n"
                "**Execution:** Prefer **calling** the next needed MCP tools in the same turn over long “I will…” preambles. "
                "Do **not** repeat **atlassianUserInfo** or identical **addCommentToJiraIssue** in one turn.\n"
                "**Jira issue payload:** Call **getJiraIssue at most once per issue key** (e.g. GPS-7525) per stage "
                "unless you know the issue changed; reuse the JSON from earlier tool messages and the conversation thread "
                "— do **not** repeat **getAccessibleAtlassianResources** or **getJiraIssue** for the same key without cause.\n"
                "**Stage 4 — Executor (Qase run + results):** You **must** create a real Qase test run via Qase MCP **`create_run`** "
                "with a real **`code`** (Qase project short code from **`list_projects`** or from the server `.env` hint `QASE_PROJECT_CODE`) — "
                "**never** `your_project_code`, `PROJECT`, or other schema filler text. "
                "Use the numeric **`run_id`** returned in the MCP/tool JSON — **never** placeholders like "
                "`AUTO_GENERATED_ID`, `TBD`, or guessed ids. After executing cases, call **`complete_run`** with that same id. "
                "Publish **per-case** results with **step-level** detail: use **`get_case`** for step text, capture screenshots with "
                "**Playwright MCP** `browser_take_screenshot` (per step or key assertion), upload attachments per Qase API / skill, "
                "and POST results so each step can reference screenshots (see executor skill — REST step payloads with `attachments` "
                "when MCP schemas are insufficient). Do **not** claim 100% pass or attach screenshots unless those MCP/API calls "
                "actually succeeded. Final chat summary must list **repo-relative** script paths from the Automation output "
                "(e.g. `tests/<feature>/tc-366-….spec.ts`) and the real **`qase_run_id`**.\n"
                "**Visible browser:** Stages that execute in a browser must **call Playwright MCP** (`browser_navigate`, …). "
                "If Chainlit shows no **browser_*** tool steps, nothing launched. If tools run but no window appears, the Playwright MCP "
                "process is likely **headless** — remove `--headless` from its MCP args and set **`PLAYWRIGHT_MCP_HEADLESS=false`** "
                "(see README / `.env.example`). When the user asks for **headed** mode, ensure the Playwright MCP server is started "
                "without headless / with `PLAYWRIGHT_MCP_HEADLESS=false`, then call **`browser_navigate`** to the resolved URL.\n"
                f"**Repo paths:** `tests/…` and `tests/pages/…` are relative to the project root **`{_PROJECT_ROOT}`** (absolute base on disk).\n"
                + _pr_url_contract
                + "**Git / GitHub:** If the user asks to push generated tests, use **workspace file tools** to write files under that root, "
                "then **`git`** in a terminal **or** **GitHub MCP** (`GITHUB_TOKEN` / `GH_PAT` in `.env`) — do **not** claim you have no "
                "way to push when repo tools or GitHub MCP are available. "
                "For GitHub MCP **`get_file_contents`** and similar calls, use the **owner** and **repo** from "
                "**`GITHUB_REPOSITORY`** (or **`git remote origin`** on this app) / `.env` splits / **`get_me`** / **`search_repositories`** — "
                "**never** fictional values like **`username`** / **`repository`** (those produce 404).\n"
                "**Identifiers:** **`TC-377`**-style ids are **Qase** public case labels, **not** Jira — use **Qase `get_case`**, "
                "not **`getJiraIssue`**.\n"
            )
            if _routing_has_qase_tools(routing):
                system_body += (
                    "**Qase designer / test artifacts:** You **must** invoke **Qase MCP** operations to create or update "
                    "real test entities (e.g. suites/cases as exposed by the connection). Status-only **addCommentToJiraIssue** "
                    "does **not** satisfy Qase designer output — use Qase MCP for test design work. "
                    "In one workflow/chat: **one** suite per project + suite title — reuse **`suite_id`** from earlier tool "
                    "results across MCP rounds; do not call **`create_suite`** again with the same naming pattern. "
                    "For cases, reuse **`list_cases`** / thread history before re-**`create_case`** with the same payload.\n"
                    "**`create_case` validation:** The Qase MCP schema may describe `priority` / `type` / `behavior` / "
                    "`automation` as English strings; many projects still require **numeric ids** or reject unknown strings. "
                    "**Default:** omit those fields on first create (use `code`, `title`, `suite_id`, description, "
                    "preconditions, `steps` only); after success, add integers from **`get_case`** / **`list_cases`** in the "
                    "same project — **not** guessed words like `\"medium\"`, `\"validation\"`, `\"automated\"`. "
                    "**Never** put Jira **`cloudId`** or **`issueIdOrKey`** into Qase tool arguments (Chainlit strips them if "
                    "the model sends them).\n"
                    "**`steps`:** Each element must include **`action`**. Use **≥3** steps for normal flows and add "
                    "**`expected_result`** on each step for test-design quality."
                )
                if _qase_api_token_in_env():
                    system_body += (
                        " **`QASE_API_TOKEN` is present** — execute Qase tools directly; do **not** loop on asking the user to "
                        "confirm credentials or “proceed” when they already said yes."
                    )
                    if _env_truthy("CHAINLIT_ASK_USER_TOOL", default=False) and any(
                        r == _CHAINLIT_ASK_USER_OP for (_m, r) in routing.values()
                    ):
                        system_body += " Use **chainlit_ask_user** only for decisions MCP cannot represent."
        elif gap_focus:
            system_body += (
                "\n\n**Gap / requirement analysis:** Call **getJiraIssue exactly once** for the active issue key "
                "(from the current message or the thread above). For linked work use **searchJiraIssuesUsingJql** or data "
                "already returned. **Do not** call getJiraIssue again for that same key — reuse the earlier tool JSON."
            )
        system_body += note

        if skill_block:
            system_body = skill_block + "\n\n---\n\n" + system_body

        gj_oai_session = _openai_tool_name_for_mcp_operation(routing, "getJiraIssue")
        if gj_oai_session and _looks_like_jira_issue_key(jira_detect_blob):
            system_body += (
                f"\n\n**This session's Jira read tool:** Call **`{gj_oai_session}`** (that exact string is the OpenAI "
                "**function.name** for getJiraIssue). Do **not** ask the user to supply tool names, prefixes, or "
                "`Rovo_MCP__…` guesses — execute MCP with the tools already attached to this chat turn."
            )

    user_for_model = _user_message_with_qase_instructions(
        _user_message_with_jira_mcp_instructions(user_text),
        thread_h,
    )
    if not _is_openai_setup_starter_message(user_text):
        user_for_model += _workflow_env_hints()
    if thread_h and _looks_like_jira_issue_key(thread_h) and not _looks_like_jira_issue_key(user_text):
        k = _last_jira_key_in_text(thread_h) or _first_jira_key_in_text(thread_h)
        if k:
            user_for_model += (
                f"\n\n[Thread context: this conversation already includes Jira issue **{k}** — use it for MCP and "
                "analysis; do not ask for the issue key again unless the user switches to a different ticket.]"
            )

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_body}]
    messages.extend(_chainlit_thread_openai_rows())
    messages.append({"role": "user", "content": user_for_model})

    # OpenAI tool_choice when enabled; tool execution is MCP call_tool or Chainlit AskUserMessage.
    require_mcp_for_issue_key = _env_truthy(
        "CHAINLIT_REQUIRE_TOOLS_FOR_ISSUE_KEY",
        default=_heuristic_require_jira_fetch_tools(user_text, jira_detect_blob),
    )
    if openai_setup_only:
        require_mcp_for_issue_key = False
    require_mcp_for_qase = _env_truthy("CHAINLIT_REQUIRE_TOOLS_FOR_QASE", default=False)
    has_get_jira_issue_tool = any(
        real == "getJiraIssue" for (_mcp, real) in routing.values()
    )
    jira_get_issue_seen = False
    qase_tool_invoked = False
    mcp_read_cache: dict[str, str] = {}
    add_comment_per_issue_turn: dict[str, int] = {}
    jira_issue_keys_fetched: set[str] = set()
    primary_jira_fetched = False

    n_tools = len(tool_specs)
    if openai_setup_only:
        await cl.Message(
            content=(
                f"**Step 3/3:** Calling OpenAI (`{model}`) **with no MCP tools** (short text summary). "
                f"HTTP timeout **{openai_timeout:.0f}s** (`CHAINLIT_OPENAI_TIMEOUT`)."
            ),
        ).send()
    else:
        await cl.Message(
            content=(
                f"**Step 3/3:** Calling OpenAI (`{model}`) with **{n_tools}** MCP tool(s). "
                f"The first response can take **30–120s** with large tool lists; HTTP timeout is **{openai_timeout:.0f}s** "
                "(`CHAINLIT_OPENAI_TIMEOUT`). If you hit timeout errors, raise that value."
            ),
        ).send()

    routing_complete = dict(routing)

    for round_i in range(max(1, max_rounds)):
        _cap_system_prompt_if_needed(messages, thread_h)
        _compact_messages_for_openai(messages, thread_h)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tool_specs:
            kwargs["tools"] = _normalize_openai_tools_for_chat_api(
                tool_specs
            )  # guaranteed ``type`` + ``function`` shape (avoids API 400 on tools[0].type)
            issue_key = _looks_like_jira_issue_key(jira_detect_blob)
            gj_oai = _openai_tool_name_for_mcp_operation(routing, "getJiraIssue") or _openai_tool_name_for_mcp_operation(
                routing_complete, "getJiraIssue"
            )
            if issue_key and require_mcp_for_issue_key:
                # `tool_choice: "required"` alone allows *any* tool (e.g. atlassianUserInfo). Force getJiraIssue by name.
                if gj_oai and has_get_jira_issue_tool and not jira_get_issue_seen:
                    if round_i == 0:
                        kwargs["tool_choice"] = {"type": "function", "function": {"name": gj_oai}}
                    else:
                        kwargs["tool_choice"] = "auto"
                elif has_get_jira_issue_tool:
                    kwargs["tool_choice"] = "required" if not jira_get_issue_seen else "auto"
                else:
                    kwargs["tool_choice"] = "required" if round_i == 0 else "auto"
            elif (
                _user_mentions_qase(thread_h)
                and require_mcp_for_qase
                and _routing_has_qase_tools(routing)
                and not issue_key
                and not qase_tool_invoked
            ):
                kwargs["tool_choice"] = "required"
            else:
                kwargs["tool_choice"] = "auto"
            if "tool_choice" in kwargs:
                _sanitize_tool_choice_function_name(kwargs["tool_choice"])
        _sanitize_assistant_tool_calls_in_messages(messages)

        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as e:
            detail = _format_connect_exception(e)
            low = detail.lower()
            if "tools[0].type" in low or "tools[0].type" in detail:
                return (
                    "OpenAI rejected the **tools** payload (`tools[0].type` missing or invalid). "
                    "This build normalizes MCP tools before each request — pull the latest `app.py` and restart Chainlit. "
                    "If it persists, capture the model name and `CHAINLIT_OPENAI_BASE_URL` (custom gateways must accept "
                    "standard Chat Completions `tools` with `type: function`).\n\n"
                    f"---\n{detail}"
                )
            if "array_above_max_length" in low or (
                "tools" in low and "maximum length" in low and "128" in detail
            ):
                cap = _openai_chat_completions_tools_cap()
                return (
                    "OpenAI rejected the request: the **`tools` array is too long** "
                    f"(Chat Completions allows at most **{cap}** tools).\n\n"
                    "**Fix:** Lower `CHAINLIT_MCP_MAX_TOOLS` / `CHAINLIT_MCP_MAX_TOOLS_WORKFLOW`, "
                    "or disconnect MCP servers you do not need for this chat. "
                    f"Optional: `CHAINLIT_OPENAI_MAX_TOOLS` (default {cap}, capped at 128 for the public API).\n\n"
                    f"---\n{detail}"
                )
            if "context" in low and ("length" in low or "max" in low or "token" in low):
                return (
                    "OpenAI **context window exceeded** (skills + tool list + MCP results in this chat turn).\n\n"
                    "**Reduce size:**\n"
                    "- `CHAINLIT_SKILLS_MAX_CHARS` / `CHAINLIT_SKILLS_MAX_CHARS_WORKFLOW` (full-workflow default is tighter)\n"
                    "- `CHAINLIT_MCP_TOOL_RESULT_MAX_CHARS` / `_WORKFLOW` (defaults: 12000 / 8000) + `CHAINLIT_MCP_TOOL_LEGACY_MAX_CHARS` for older steps\n"
                    "- `CHAINLIT_OPENAI_FUNCTION_DESC_MAX` (default 512)\n"
                    "- `CHAINLIT_MCP_MAX_TOOLS` / `_WORKFLOW` (defaults: 35 / 28; OpenAI caps tools at 128)\n"
                    "- `CHAINLIT_SKILL_PROFILE=orchestrator` or `CHAINLIT_DISABLE_SKILLS=1` for a minimal system prompt\n"
                    "- Or use a model with a **larger** context than 128k.\n\n"
                    f"---\n{detail}"
                )
            if "function.name" in low and "pattern" in low:
                return (
                    "OpenAI rejected a **tool_calls.function.name** in the chat history (must match "
                    "`^[a-zA-Z0-9_-]+$`). This build sanitizes names before each request — restart Chainlit. "
                    "If it persists, start a **new chat** (stale thread state from an older build).\n\n"
                    f"---\n{detail}"
                )
            hint = (
                "\n\nCorporate network / SSL:\n"
                "- `CHAINLIT_SSL_CA_BUNDLE` or `SSL_CERT_FILE` = path to corporate `.pem`\n"
                "- Or `CHAINLIT_OPENAI_VERIFY_SSL=0` (dev only)\n"
                "- `HTTPS_PROXY` if the browser uses a proxy\n"
                "- Azure: `CHAINLIT_OPENAI_BASE_URL` + matching model deployment name\n"
            )
            return (
                f"OpenAI chat.completions failed ({openai_timeout}s budget on httpx client):\n\n{detail}\n\n"
                "Check VPN/firewall and `OPENAI_API_KEY`."
                + hint
            )
        choice = resp.choices[0].message
        if choice.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": choice.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": _sanitize_oai_tool_function_name(tc.function.name or ""),
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in choice.tool_calls
                    ],
                }
            )
            def _tool_call_order(tc: Any) -> tuple[int, str]:
                """Prefer getJiraIssue before addCommentToJiraIssue in the same assistant message."""
                fn_raw = tc.function.name or ""
                fn, route_tbl = _resolve_tool_call_to_routing_table(fn_raw, routing, routing_complete)
                if not fn or not route_tbl:
                    return (1, fn_raw)
                _m, real = route_tbl[fn]
                if real == "getJiraIssue":
                    return (0, fn_raw)
                if real == "addCommentToJiraIssue":
                    return (2, fn_raw)
                return (1, fn_raw)

            _tcs = sorted(choice.tool_calls, key=_tool_call_order)
            for tc in _tcs:
                fn_raw = tc.function.name or ""
                fn, route_tbl = _resolve_tool_call_to_routing_table(fn_raw, routing, routing_complete)
                raw_args = tc.function.arguments or "{}"
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    args = {}
                if not route_tbl or not fn or fn not in route_tbl:
                    tool_text = (
                        f"Unknown MCP routing entry from model: {fn_raw!r}. "
                        "Expected a name from the current tools list (`<connection>__<operation>`; "
                        "dots like `conn.getJiraIssue` map to `conn__getJiraIssue`; hyphens vs underscores in the "
                        "connection id are normalized). If **getJiraIssue** is missing from the tool list, raise "
                        "`CHAINLIT_MCP_MAX_TOOLS` or reconnect Atlassian MCP."
                    )
                else:
                    mcp_conn, real_name = route_tbl[fn]
                    if isinstance(args, dict):
                        if _mcp_ui_bucket(mcp_conn) == "jira":
                            _normalize_atlassian_cloud_id_in_args(args)
                            _force_env_jira_cloud_id_for_atlassian_mcp(args, mcp_conn)
                        elif _mcp_connection_or_op_is_qase(mcp_conn, real_name):
                            _strip_jira_leakage_from_qase_mcp_args(args)
                        args = _prepare_github_mcp_tool_args(mcp_conn, real_name, args)
                    if mcp_conn == _CHAINLIT_MCP_PLACEHOLDER and real_name == _CHAINLIT_ASK_USER_OP:
                        tool_text = await _run_chainlit_ask_user(args)
                    else:
                        if _mcp_connection_or_op_is_qase(mcp_conn, real_name):
                            qase_tool_invoked = True
                        mcp_wrap = ws.mcp_sessions.get(mcp_conn)
                        if not mcp_wrap:
                            tool_text = f"MCP connection {mcp_conn!r} is gone."
                        else:
                            try:
                                _step_preview = int(os.getenv("CHAINLIT_MCP_STEP_OUTPUT_MAX", "12000"))
                                use_dedup = (
                                    _env_truthy("CHAINLIT_MCP_DEDUP_IDENTICAL_CALLS", default=True)
                                    and real_name in _MCP_DEDUP_IDENTICAL_CALLS_TOOLS
                                )
                                ck = _mcp_read_cache_key(mcp_conn, real_name, args)
                                blocked_add_no_fetch = False
                                if real_name == "addCommentToJiraIssue":
                                    if _env_truthy("CHAINLIT_REQUIRE_GET_JIRA_BEFORE_ADD_COMMENT", default=True):
                                        ik_block = (
                                            _issue_key_from_jira_mcp_args(args)
                                            or str(args.get("issueIdOrKey", "") or "").strip()
                                        )
                                        if ik_block and ik_block.upper() not in jira_issue_keys_fetched:
                                            blocked_add_no_fetch = True
                                sess_hit = (
                                    _session_mcp_read_cache_get(ck)
                                    if _session_cacheable_mcp_tool(real_name)
                                    else None
                                )
                                if blocked_add_no_fetch:
                                    ik_b = (
                                        _issue_key_from_jira_mcp_args(args)
                                        or str(args.get("issueIdOrKey", "") or "").strip()
                                    )
                                    tool_text = (
                                        f"[Blocked — call **getJiraIssue** for **{ik_b}** before `addCommentToJiraIssue`. "
                                        "Planner skill: fetch issue JSON first, then **one** gap-report comment when ready. "
                                        "Do not use Jira comments for progress narration; put status in the assistant reply.]"
                                    )
                                    if _env_truthy("CHAINLIT_MCP_STEP_ON_ADD_COMMENT_BLOCK", default=False):
                                        async with cl.Step(
                                            name=_mcp_chainlit_step_title(
                                                mcp_conn, real_name, args, suffix=" (blocked)"
                                            ),
                                            type="run",
                                            tags=_mcp_chainlit_step_tags(mcp_conn, ["blocked"], real_name),
                                            default_open=False,
                                        ) as mcp_step:
                                            mcp_step.input = args
                                            mcp_step.output = (
                                                tool_text
                                                if len(tool_text) <= _step_preview
                                                else tool_text[:_step_preview] + "…"
                                            )
                                elif (
                                    _real_name_is_get_jira_issue(real_name)
                                    and isinstance(args, dict)
                                    and _env_truthy("CHAINLIT_BLOCK_GET_JIRA_FOR_TC_KEYS", default=True)
                                    and _looks_like_qase_tc_public_id(_raw_jira_issue_selector_from_args(args))
                                ):
                                    _ik_tc = _raw_jira_issue_selector_from_args(args)
                                    tool_text = (
                                        f"[Blocked — **{_ik_tc}** is a **Qase** public id (**TC-<number>**), not a Jira issue key. "
                                        "Use **Qase MCP** **`get_case`** (project **code** + case id per schema). "
                                        "Use **getJiraIssue** only for Jira keys (e.g. **GPS-7525**).]"
                                    )
                                elif sess_hit:
                                    tool_text = (
                                        "[Session cache — this MCP read already succeeded earlier in this chat. "
                                        "Reuse the JSON below; do not call the same read again unless you need fresh data.]\n\n"
                                        + sess_hit
                                    )
                                    async with cl.Step(
                                        name=_mcp_chainlit_step_title(
                                            mcp_conn, real_name, args, suffix=" (session cache)"
                                        ),
                                        type="run",
                                        tags=_mcp_chainlit_step_tags(
                                            mcp_conn, ["cached", "session-cache"], real_name
                                        ),
                                        default_open=_mcp_step_default_open(mcp_conn, real_name),
                                    ) as mcp_step:
                                        mcp_step.input = args
                                        mcp_step.output = (
                                            tool_text
                                            if len(tool_text) <= _step_preview
                                            else tool_text[:_step_preview] + "…"
                                        )
                                elif (
                                    _env_truthy("CHAINLIT_MCP_SESSION_DEDUP_QASE_CREATES", default=True)
                                    and _mcp_connection_or_op_is_qase(mcp_conn, real_name)
                                    and real_name in ("create_suite", "create_case")
                                    and isinstance(args, dict)
                                    and (_qck := _qase_create_session_cache_key(mcp_conn, real_name, args))
                                    and (_qase_hit := _session_qase_create_cache_get(_qck))
                                ):
                                    tool_text = (
                                        "[Session duplicate skipped — this Chainlit chat already ran a successful "
                                        f"**{real_name}** for the same logical key; reuse suite/case ids from the "
                                        "JSON below. Do not create the same suite or duplicate case payload again.]\n\n"
                                        + _qase_hit
                                    )
                                    async with cl.Step(
                                        name=_mcp_chainlit_step_title(
                                            mcp_conn, real_name, args, suffix=" (session dedup)"
                                        ),
                                        type="run",
                                        tags=_mcp_chainlit_step_tags(
                                            mcp_conn, ["cached", "session-dedup"], real_name
                                        ),
                                        default_open=_mcp_step_default_open(mcp_conn, real_name),
                                    ) as mcp_step:
                                        mcp_step.input = args
                                        mcp_step.output = (
                                            tool_text
                                            if len(tool_text) <= _step_preview
                                            else tool_text[:_step_preview] + "…"
                                        )
                                elif use_dedup and ck in mcp_read_cache:
                                    tool_text = (
                                        "[Duplicate MCP call skipped — same operation and arguments already ran earlier "
                                        "in this turn.]\n\n" + mcp_read_cache[ck]
                                    )
                                    async with cl.Step(
                                        name=_mcp_chainlit_step_title(
                                            mcp_conn, real_name, args, suffix=" (cached)"
                                        ),
                                        type="run",
                                        tags=_mcp_chainlit_step_tags(mcp_conn, ["cached"], real_name),
                                        default_open=_mcp_step_default_open(mcp_conn, real_name),
                                    ) as mcp_step:
                                        mcp_step.input = args
                                        mcp_step.output = (
                                            tool_text
                                            if len(tool_text) <= _step_preview
                                            else tool_text[:_step_preview] + "…"
                                        )
                                else:
                                    limit_hit = False
                                    max_ac_for_msg = 0
                                    if real_name == "addCommentToJiraIssue":
                                        try:
                                            max_ac_for_msg = int(
                                                os.getenv("CHAINLIT_MCP_MAX_ADD_COMMENT_PER_TURN", "1")
                                            )
                                        except ValueError:
                                            max_ac_for_msg = 1
                                        if max_ac_for_msg > 0:
                                            ik_slot = (
                                                _issue_key_from_jira_mcp_args(args)
                                                or str(args.get("issueIdOrKey", "") or "").strip()
                                            )
                                            slot_key = f"{mcp_conn}\x1f{ik_slot}"
                                            n_ac = add_comment_per_issue_turn.get(slot_key, 0)
                                            if n_ac >= max_ac_for_msg:
                                                limit_hit = True
                                            else:
                                                add_comment_per_issue_turn[slot_key] = n_ac + 1
                                    if limit_hit:
                                        tool_text = (
                                            "[Skipped — `addCommentToJiraIssue` per-issue limit for this chat turn reached "
                                            f"({max_ac_for_msg} max; set `CHAINLIT_MCP_MAX_ADD_COMMENT_PER_TURN` or `0` for "
                                            "unlimited). Planner skill: **getJiraIssue** first, then **one** final gap-report "
                                            "comment — not progress narration. Put status in the assistant message.]"
                                        )
                                        if _env_truthy("CHAINLIT_MCP_STEP_ON_ADD_COMMENT_LIMIT", default=False):
                                            async with cl.Step(
                                                name=_mcp_chainlit_step_title(
                                                    mcp_conn, real_name, args, suffix=" (limit)"
                                                ),
                                                type="run",
                                                tags=_mcp_chainlit_step_tags(mcp_conn, ["limit"], real_name),
                                                default_open=False,
                                            ) as mcp_step:
                                                mcp_step.input = args
                                                mcp_step.output = (
                                                    tool_text
                                                    if len(tool_text) <= _step_preview
                                                    else tool_text[:_step_preview] + "…"
                                                )
                                    else:
                                        if _mcp_connection_or_op_is_qase(mcp_conn, real_name) and _env_truthy(
                                            "CHAINLIT_MCP_QASE_STATUS_MESSAGES", default=False
                                        ):
                                            await cl.Message(
                                                content=(
                                                    f"**{_mcp_chainlit_step_title(mcp_conn, real_name, args)}** "
                                                    "— calling Qase MCP…"
                                                ),
                                            ).send()
                                        async with cl.Step(
                                            name=_mcp_chainlit_step_title(mcp_conn, real_name, args),
                                            type="run",
                                            tags=_mcp_chainlit_step_tags(mcp_conn, [], real_name),
                                            default_open=_mcp_step_default_open(mcp_conn, real_name),
                                        ) as mcp_step:
                                            mcp_step.input = args
                                            result = await mcp_wrap.client.call_tool(
                                                real_name,
                                                arguments=args,
                                                read_timeout_seconds=timedelta(seconds=call_tool_timeout),
                                            )
                                            tool_text = _tool_result_to_text(result)
                                            if use_dedup:
                                                mcp_read_cache[ck] = tool_text
                                            if _session_cacheable_mcp_tool(real_name) and _should_cache_mcp_tool_result(
                                                tool_text
                                            ):
                                                _session_mcp_read_cache_put(ck, tool_text)
                                            if (
                                                _env_truthy(
                                                    "CHAINLIT_MCP_SESSION_DEDUP_QASE_CREATES", default=True
                                                )
                                                and _mcp_connection_or_op_is_qase(mcp_conn, real_name)
                                                and real_name in ("create_suite", "create_case")
                                                and isinstance(args, dict)
                                            ):
                                                _qk = _qase_create_session_cache_key(mcp_conn, real_name, args)
                                                if _qk and _should_cache_mcp_tool_result(tool_text):
                                                    _session_qase_create_cache_put(_qk, tool_text)
                                            preview = (
                                                tool_text
                                                if len(tool_text) <= _step_preview
                                                else tool_text[:_step_preview] + "…"
                                            )
                                            mcp_step.output = preview
                            except Exception as e:
                                tool_text = f"MCP call_tool error: {e!s}"
                if (
                    strip_gji_after_primary
                    and primary_issue_key
                    and route_tbl is not None
                    and fn
                    and fn in route_tbl
                    and route_tbl[fn][1] == "getJiraIssue"
                ):
                    _ik = _issue_key_from_jira_mcp_args(args)
                    if (
                        _ik
                        and _ik == primary_issue_key
                        and not str(tool_text).startswith("MCP call_tool error")
                    ):
                        primary_jira_fetched = True
                if fn and route_tbl and fn in route_tbl:
                    _, r_n = route_tbl[fn]
                    _register_jira_get_fetched_if_ok(r_n, args, tool_text, jira_issue_keys_fetched)
                    if r_n == "getJiraIssue":
                        _gji_out = str(tool_text)
                        if not _gji_out.startswith("MCP call_tool error") and not _gji_out.startswith(
                            "[Blocked"
                        ):
                            jira_get_issue_seen = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _truncate_tool_text_for_model(tool_text, jira_detect_blob),
                    }
                )
            if strip_gji_after_primary and primary_jira_fetched:
                tool_specs, routing = _strip_get_jira_issue_tools(tool_specs, routing)
                has_get_jira_issue_tool = any(
                    r == "getJiraIssue" for (_m, r) in routing.values()
                )
            continue

        text = (choice.content or "").strip()
        if text:
            # Model sometimes returns plans ("I will call getJiraIssue…") with **no** tool_calls when
            # ``tool_choice`` was auto or ignored — do not surface that as a final answer if Jira is required.
            if (
                tool_specs
                and _looks_like_jira_issue_key(jira_detect_blob)
                and require_mcp_for_issue_key
                and has_get_jira_issue_tool
                and not jira_get_issue_seen
                and round_i + 1 < max(1, max_rounds)
            ):
                messages.append({"role": "assistant", "content": text})
                gj = _openai_tool_name_for_mcp_operation(routing, "getJiraIssue")
                if gj:
                    nudge = (
                        f"You must **call** the Jira tool now: use **`{gj}`** with **issueIdOrKey** (and **cloudId**). "
                        "Respond with **tool_calls only** for this step — no narration."
                    )
                else:
                    nudge = (
                        "You must **call** **getJiraIssue** on the Atlassian MCP connection now (exact name from the "
                        "tools list). Use **tool_calls only** for this step — no narration."
                    )
                messages.append({"role": "user", "content": nudge})
                continue
            return text
        return (
            "(No assistant text after MCP rounds — the model returned an empty message. "
            f"Try rephrasing; round {round_i + 1}/{max_rounds}.)"
        )

    return (
        f"Stopped after {max_rounds} MCP interaction rounds. "
        "Increase `CHAINLIT_MCP_MAX_ROUNDS` (or `CHAINLIT_MCP_MAX_ROUNDS_WORKFLOW` for full-pipeline phrases), "
        "or `CHAINLIT_CHAT_TOTAL_TIMEOUT` / `CHAINLIT_CHAT_TOTAL_TIMEOUT_WORKFLOW` if the chat hit the wall-clock limit."
    )


@cl.set_starter_categories
async def _workflow_starter_categories(
    user: cl.User | None = None,
    language: str | None = None,
) -> list[cl.StarterCategory]:
    """Quick prompts aligned with `.github/skills` (orchestrator → planner → qase → automation → executor → healer)."""
    return [
        cl.StarterCategory(
            label="Pipeline",
            starters=[
                cl.Starter(
                    label="Full pipeline (Jira key)",
                    message=(
                        "Run the **full human-loop QA pipeline** for **one Jira issue** in this chat. "
                        "You will be asked for the **Jira issue key** next (do not use template keys like `PROJ-123`). "
                        "Follow `.github/skills/orchestrator/SKILL.md`: Planner → Qase designer → Automation → Executor → Healer. "
                        "Use MCP only for facts; call **getJiraIssue** when the skill needs issue JSON; use Qase and Playwright MCP in their stages."
                    ),
                ),
                cl.Starter(
                    label="Orchestrator — one issue end-to-end",
                    message=(
                        "**Orchestrator:** Run every stage in order in this same Chainlit session for **one Jira issue**, "
                        "pass prior stage JSON forward, and stop for human approval only where the skill says so. "
                        "You will be prompted for the **Jira issue key** first."
                    ),
                ),
            ],
        ),
        cl.StarterCategory(
            label="Single stage",
            starters=[
                cl.Starter(
                    label="Planner — gap analysis",
                    message=(
                        "**Planner only:** Fetch the Jira issue you specify via MCP, run gap analysis per `.github/skills/planner/SKILL.md`, "
                        "and output structured planner JSON (requirements, gaps, environment_details). "
                        "You will be asked for the **Jira issue key** first."
                    ),
                ),
                cl.Starter(
                    label="Qase designer — cases & suites",
                    message=(
                        "**Qase designer only:** For the Jira scope you provide, design tests per `.github/skills/qase-designer/SKILL.md`. "
                        "You will be asked for the **Jira issue key** first. "
                        "Use **Qase MCP** to create or update suites and cases; use **`get_case`** for Qase ids like **TC-380**, not Jira **getJiraIssue**."
                    ),
                ),
                cl.Starter(
                    label="Automation — Playwright + POM",
                    message=(
                        "**Automation only:** Inspect the live app with **Playwright MCP** (headed if configured), "
                        "then write specs under `tests/<feature>/` and page objects under `tests/pages/` per `.github/skills/automation/SKILL.md`. "
                        "You will be asked for the **Jira issue key** and a **feature folder slug** next."
                    ),
                ),
                cl.Starter(
                    label="Executor — Qase run + results",
                    message=(
                        "**Executor only:** Create a real Qase run via MCP **`create_run`**, execute linked Playwright scripts, "
                        "attach screenshots per step where required, and **`complete_run`** with accurate per-case results per `.github/skills/executor/SKILL.md`."
                    ),
                ),
                cl.Starter(
                    label="Healer — failures & defects",
                    message=(
                        "**Healer only:** Analyze the latest failure output, classify root cause per `.github/skills/healer/SKILL.md`, "
                        "propose locator or timing fixes for automation issues, and use Jira MCP for real product defects when appropriate."
                    ),
                ),
            ],
        ),
        cl.StarterCategory(
            label="Setup",
            starters=[
                cl.Starter(
                    label="OpenAI / LLM check",
                    message=(
                        "**Setup — OpenAI:** Confirm this Chainlit app can reach the LLM. "
                        "Check `.env` has **`OPENAI_API_KEY`** (or Azure **`CHAINLIT_OPENAI_BASE_URL`** + key if used). "
                        "If Step 1/3 fails on TLS/proxy: **`CHAINLIT_OPENAI_VERIFY_SSL=0`**, **`HTTPS_PROXY`**, or **`pip install truststore`** with **`CHAINLIT_USE_TRUSTSTORE=1`** (Windows). "
                        "If Step 3 times out with many MCP tools: raise **`CHAINLIT_OPENAI_TIMEOUT`** and review **`CHAINLIT_OPENAI_MAX_TOOLS`** in `.env.example`. "
                        "After **Step 3/3** completes, reply with a **brief** bullet summary of what the steps above proved; "
                        "only mention missing keys if a step **failed** (do not recite generic setup or other integrations)."
                    ),
                ),
                cl.Starter(
                    label="MCP plug + Playwright env",
                    message=(
                        "**Setup — MCP:** Add servers from the **plug** menu (e.g. Atlassian/Jira, Playwright; add others when a stage needs them). "
                        "For a **visible** browser: do not pass **`--headless`** to Playwright MCP; set **`PLAYWRIGHT_MCP_HEADLESS=false`** and "
                        "**`CHAINLIT_MCP_FULL_ENV=1`** so MCP child processes inherit this repo’s `.env`. "
                        "If Step 2/3 hangs listing tools, disconnect a stuck server or increase **`CHAINLIT_MCP_LIST_TOOLS_TIMEOUT`**."
                    ),
                ),
                cl.Starter(
                    label="MCP probe (local, no LLM)",
                    message="/mcp-setup",
                ),
                cl.Starter(
                    label="Workspace GitHub repo (local, no LLM)",
                    message="/github-repo",
                ),
                cl.Starter(
                    label="GitHub MCP — Copilot URL (Cursor-style)",
                    message="/github-mcp",
                ),
                cl.Starter(
                    label="Local git branches (no LLM)",
                    message="/git-branches",
                ),
            ],
        ),
    ]


@cl.on_chat_start
async def on_chat_start() -> None:
    """Expose model + skill pack in the Chainlit chat settings UI (gear icon or sidebar per config)."""
    models, model_initial = _ui_model_select_config()
    prof_initial = os.getenv("CHAINLIT_SKILL_PROFILE", "auto").strip().lower()
    valid = frozenset(
        ("auto", "orchestrator", "full", "planner", "qase-designer", "automation", "executor", "healer")
    )
    if prof_initial not in valid:
        prof_initial = "auto"
    profile_items = {
        "Auto (.env or heuristics)": "auto",
        "Orchestrator only": "orchestrator",
        "Full pipeline (all skills)": "full",
        "Planner": "planner",
        "Qase designer": "qase-designer",
        "Automation": "automation",
        "Executor": "executor",
        "Healer": "healer",
    }
    await cl.ChatSettings(
        [
            Select(
                id="chainlit_openai_model",
                label="OpenAI model",
                values=models,
                initial_value=model_initial,
                tooltip="Overrides CHAINLIT_OPENAI_MODEL for this chat session.",
            ),
            Select(
                id="chainlit_skill_profile",
                label="Skill pack (agent context)",
                items=profile_items,
                initial_value=prof_initial,
                tooltip='Choose a preset skill bundle. "Auto" uses CHAINLIT_SKILL_PROFILE or message heuristics.',
            ),
        ]
    ).send()


@cl.on_mcp_connect
async def on_mcp_connect(connection, session: ClientSession) -> None:
    """Required for MCP."""
    pass


@cl.on_mcp_disconnect
async def on_mcp_disconnect(name: str, session: ClientSession) -> None:
    pass


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """User chat: OpenAI + repo skills/rules; MCP servers execute tools (plug icon)."""
    user_text = _user_text_from_chainlit(message.content)
    thread_h = _heuristic_thread_text(user_text)

    sess = context.session
    if not isinstance(sess, WebsocketSession):
        await cl.Message(
            content="MCP routing needs a browser session (WebsocketSession).",
        ).send()
        return

    if _message_triggers_github_mcp_chainlit_instructions(user_text):
        await cl.Message(content=_github_mcp_chainlit_integration_markdown()).send()
        return

    if _message_triggers_github_repo_local(user_text):
        await cl.Message(content=_github_repo_local_report()).send()
        return

    if _message_triggers_git_branches_local(user_text):
        await cl.Message(content=_git_branches_local_report()).send()
        return

    if _message_triggers_local_mcp_probe(user_text):
        if _is_mcp_connectivity_checklist_only(user_text):
            await cl.Message(
                content=(
                    "**Setup MCP starter detected.** Running the built-in **`/mcp-setup`** probe (read-only calls per server — "
                    "**no OpenAI**). "
                    "For a silent run, send only **`/mcp-setup`** on one line.\n\n"
                    "**If GitHub returned 404:** `GITHUB_REPOSITORY` must use the **exact** repo name from github.com "
                    "(this workspace folder is often `…HumanLoop.Chainlit` while the remote may differ). "
                    "Send **`/github-repo`** for owner/repo from this checkout (**no OpenAI**). "
                    "Send **`/github-mcp`** for GitHub MCP (Copilot URL + `Authorization` header) setup like Cursor `mcp.json`."
                )
            ).send()
        report = await _run_mcp_connectivity_probe(sess)
        await cl.Message(content=report).send()
        return

    resolved_inputs = await _prompt_starter_inputs_if_needed(user_text)
    if resolved_inputs is None:
        return
    user_text = resolved_inputs
    thread_h = _heuristic_thread_text(user_text)

    total_timeout = _effective_chat_total_timeout(thread_h)
    if _is_openai_setup_starter_message(user_text):
        await cl.Message(
            content=(
                "**Step 1/3:** Ping OpenAI (~20s). **OpenAI / LLM check** skips loading MCP into the model "
                "(**Step 2** is skipped; **Step 3** is text-only) so the assistant cannot call Jira/GitHub. "
                "For MCP, use **`/mcp-setup`** or the **MCP plug + Playwright** starter. "
                "Stuck on Step 1? Set `CHAINLIT_OPENAI_VERIFY_SSL=0` or `HTTPS_PROXY` in `.env`, install `truststore`, restart."
            ),
        ).send()
    else:
        await cl.Message(
            content=(
                "**Step 1/3:** Ping OpenAI (~20s). "
                "Then you should see **OpenAI reachable**, **Step 2** (list MCP tools — parallel), and **Step 3** (call the model). "
                "Stuck on Step 1? Set `CHAINLIT_OPENAI_VERIFY_SSL=0` or `HTTPS_PROXY` in `.env`, install `truststore`, restart. "
                "Stuck on Step 2? Disconnect a hung MCP or increase `CHAINLIT_MCP_LIST_TOOLS_TIMEOUT`. "
                "Stuck on Step 3? Increase `CHAINLIT_OPENAI_TIMEOUT` (large tool + skill prompts)."
                + (
                    f"\n\nFull-workflow mode: chat timeout **{total_timeout:.0f}s** (`CHAINLIT_CHAT_TOTAL_TIMEOUT_WORKFLOW`)."
                    if _pipeline_keywords(thread_h)
                    else ""
                )
            ),
        ).send()

    try:
        reply = await asyncio.wait_for(
            _run_openai_with_mcp(user_text, sess),
            timeout=total_timeout,
        )
    except asyncio.TimeoutError:
        reply = (
            f"Stopped after {total_timeout:.0f}s (wall-clock limit). "
            "For long pipelines set `CHAINLIT_CHAT_TOTAL_TIMEOUT` or `CHAINLIT_CHAT_TOTAL_TIMEOUT_WORKFLOW` (default 900s for workflow phrases)."
        )
    await cl.Message(content=reply).send()
