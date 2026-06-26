# Build progress

This project is being built iteratively (a `/loop` over ~10 passes). This file
tracks what's done and what's next so each pass continues cleanly.

## Done

### Iteration 1 — foundation + first tools
- Project scaffold: `pyproject.toml` (uv/hatchling, src layout), `.env.example`,
  `.gitignore`, README.
- Core: `config.py` (pydantic-settings), `shell.py` (safe subprocess runner),
  `safety.py` (read-only guardrail + secret redaction + output formatting),
  `llm.py` (Claude Opus 4.8 default via langchain-anthropic; Bedrock option).
- Agent: `prompts.py` (senior-SRE triage system prompt), `agent.py`
  (`create_tool_calling_agent` + `AgentExecutor`).
- Tools: Kubernetes (9), Helm (5), Network (5). Registry in `tools/__init__.py`.
- CLI (`cli.py`, typer + rich): `triage`, `chat`, `tools`, `doctor`, `version`.

### Iteration 2 — GitHub Copilot agent + AWS/Bedrock hosting (user-requested)
- `copilot/verify.py`: GitHub request signature verification (ECDSA P-256 /
  ECDSA-NIST-P256V1-SHA256, public keys from api.github.com, X-GitHub-* headers).
- `copilot/protocol.py`: Copilot messages → agent input/history; OpenAI-style
  SSE response stream terminated by `data: [DONE]`.
- `copilot/server.py`: FastAPI app — `POST /agent` (verified, streaming),
  `GET /health`; agent built lazily and cached.
- CLI `serve` command; `server` extra (fastapi, uvicorn, cryptography).
- `Dockerfile` (+ kubectl/helm/aws) and `deploy/aws.md` (App Runner / ECS,
  Bedrock model access + IAM, Copilot app registration).
- Bedrock LLM provider verified (already in `llm.py`); docs use the
  `us.anthropic.claude-opus-4-8` inference profile.
- Tests: `tests/test_copilot.py` (protocol, SSE, signature roundtrip). 26 pass.

### Iteration 3 — Observability HTTP client + Prometheus tools
- `tools/obs_http.py`: shared HTTP helper (auth, timeout, redaction, JSON dump)
  for all observability backends.
- `tools/prometheus.py` (5 tools): instant query, range query, alerts, targets,
  label values — results formatted compactly (one line per series).
- Added `http_timeout` setting. Tests: `tests/test_prometheus.py`. 32 pass total,
  24 tools.

### Iteration 4 — Grafana + Datadog tools
- `tools/grafana.py` (4): health, search dashboards, list datasources, firing
  alerts (via Grafana's Prometheus-compatible alerting API).
- `tools/datadog.py` (4): metric query, logs search (v2), monitors (non-OK),
  events. Uses DD-API-KEY / DD-APPLICATION-KEY headers, site-derived host.
- Added shared `parse_duration` to `obs_http`. Tests in `tests/test_observability.py`.
  38 pass total, 32 tools across 6 domains.

### Iteration 5 — AWS EKS/EC2 tools
- `tools/aws.py` (8): EC2 describe-instances / instance-status / security-groups,
  EKS list-clusters / describe-cluster / list-nodegroups / describe-nodegroup,
  CloudWatch describe-alarms. Read-only `aws` CLI, parsed JSON → compact output,
  inherits the mutation guard. Tests in `tests/test_aws.py`. 46 pass, 40 tools.

### Iteration 6 — CI/CD (Jenkins) tools
- `tools/jenkins.py` (6): job status, build console-log tail, pipeline stages
  (wfapi), test report (failures), queue (blocked reasons), list jobs. HTTP basic
  auth (user + API token); added `auth=` to `obs_http.request_json`. Nested
  folder paths handled. Tests in `tests/test_jenkins.py`. 53 pass, 46 tools.

### Iteration 7 — Hosted services: Kafka / Redis / databases
- `tools/kexec.py`: guarded `pod_exec` helper (read-only client commands only,
  `allow_exec` toggle). Added `allow_exec` setting.
- `tools/kafka.py` (4): list/describe topics, list consumer groups, group lag.
- `tools/redis.py` (3): INFO (section-validated), slowlog, client list.
- `tools/databases.py` (3): connection check, read-only query (SQL validated +
  Postgres RO transaction), pg_stat_activity. `is_readonly_sql` guard.
- Tests in `tests/test_services.py`. 63 pass, 56 tools across 11 domains.

### Iteration 8 — In-cluster network triage
- `tools/k8s_network.py` (6): native (no exec) — service endpoints, list/describe
  NetworkPolicies, ingress; in-pod probes (guarded exec, argv-safe, host
  validated) — DNS via `getent hosts`, TCP via a `python3` one-liner.
- Tests in `tests/test_k8s_network.py`. 69 pass, 62 tools across 12 domains.
- Also fixed (during local/Copilot/Bedrock testing): Copilot `/agent` now streams
  credential/build errors as SSE instead of a 500; Bedrock init raises a clear
  export-credentials hint.

### Iteration 9 — Correlation helpers + report polish
- `tools/correlation.py` (2): `incident_snapshot` (composes k8s events + Prom/
  Grafana alerts + Datadog monitors/events, skips unconfigured backends) and
  `cluster_health_overview` (nodes + not-Running pods + Warning events).
  Registered first so the agent reaches for them on broad incidents.
- System prompt updated to start broad incidents with the snapshot tools.
- Tests in `tests/test_correlation.py`. 72 pass, 64 tools across 13 domains.

### Iteration 10 — Hardening, tests, CI pipeline, GitHub Models provider
- **Tool-group trimming**: `tools_for(names)` in `tools/__init__.py`;
  `selected_groups()` in `config.py`; `--groups` flag on `triage` + `chat`.
- **JSON output**: `TriageResult.to_dict()` + `-o json` on `triage` command.
- **GitHub Models LLM provider**: `_build_github()` in `llm.py`; `github` extra;
  `github_token`/`github_models_url`/`github_model` settings; `doctor` updated.
  Lets users run/test locally with just a GitHub PAT — no Anthropic key or AWS.
- **langchain 1.x regression guard**: pinned `langchain<1.0` across all packages
  after 1.x removed `AgentExecutor`/`create_tool_calling_agent`.
- **Tests added**: `test_llm.py`, `test_agent.py` — real `build_agent` construction
  used as ongoing regression guard. Total: **79 tests, 64 tools, 13 domains**.
- **CI pipeline**:
  - `.github/workflows/ci.yml` — GitHub Actions: install uv, sync extras
    `dev+server+github`, run `ruff check`, `pytest -q`, docker build on main.
  - `Jenkinsfile` — declarative pipeline: python:3.12 container, same steps.
- All checks pass: ruff clean, 79/79 green.

## COMPLETE ✓
64 tools across 13 domains, 79 tests, 3 LLM providers (anthropic/bedrock/github),
GitHub Copilot agent protocol (FastAPI SSE server with ECDSA signature
verification), Dockerfile + deploy/aws.md for Bedrock hosting, full CI pipeline.

## Notes / decisions
- No MCP anywhere (hard constraint). All capabilities are custom LangChain tools.
- Read-only by default; mutations gated behind an explicit flag.
- LLM defaults to Claude Opus 4.8 (`claude-opus-4-8`) with adaptive thinking.

## Notes / decisions
- No MCP anywhere (hard constraint). All capabilities are custom LangChain tools.
- Read-only by default; mutations gated behind an explicit flag.
- LLM defaults to Claude Opus 4.8 (`claude-opus-4-8`) with adaptive thinking.
