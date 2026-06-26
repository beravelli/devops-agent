# DevOps Triage Agent

A LangChain **tool-calling agent** that triages production issues across CI/CD,
networking, Kubernetes, Helm, AWS (EKS/EC2), hosted services (Kafka, Redis,
databases), and observability (Grafana / Prometheus / Datadog).

Every capability is a **hand-written custom tool** — there is **no MCP** anywhere
in this project. Tools shell out to the CLIs you already have (`kubectl`,
`helm`, `aws`) or call backend HTTP APIs directly, so the agent works inside
locked-down environments where MCP isn't an option.

It is **read-only by default**: the agent gathers evidence and recommends fixes,
but refuses to run state-changing commands unless you explicitly opt in.

## How it works

```
            ┌────────────────────────────────────────────────┐
  incident  │  AgentExecutor (LangChain)                      │
  ────────► │   • Claude Opus 4.8 (adaptive thinking)         │
  question  │   • system prompt = senior SRE triage playbook  │
            │   • picks tools, reads results, correlates      │
            └───────────────┬────────────────────────────────┘
                            │ tool calls
        ┌───────────────────┼───────────────────────────────┐
        ▼                   ▼                                ▼
   kubectl/helm        HTTP backends                  pure-Python checks
   (subprocess)        (Prometheus, Grafana,          (DNS, TCP, HTTP)
                        Datadog, Jenkins)
```

### LLM providers

The agent is provider-agnostic (LangChain). Pick one via `DEVOPS_AGENT_LLM_PROVIDER`:

| Provider | Needs | Model |
|---|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY` | Claude Opus 4.8 |
| `bedrock` | AWS creds + Bedrock model access | `us.anthropic.claude-opus-4-8` |
| `github` | a GitHub token with **`models: read`** | e.g. `openai/gpt-4o` |

**No Anthropic key and no AWS?** Use `github` — it calls [GitHub Models](https://github.com/marketplace/models)
(OpenAI-compatible, free tier) and runs the whole agent locally with just a
GitHub token.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/). `kubectl`, `helm`,
and `aws` should be on your PATH and pointed at the right cluster/account.

```bash
uv sync                 # core (Anthropic provider)
uv sync --extra github  # to use GitHub Models (no Anthropic key / AWS needed)
uv sync --extra bedrock # to use Claude on Amazon Bedrock
uv sync --extra server  # to run the GitHub Copilot agent HTTP server
uv sync --extra dev     # tests + linters

cp .env.example .env    # then set a credential for your chosen provider
```

## Use

```bash
# One-shot triage
uv run devops-agent triage "payments pods are CrashLoopBackOff in the prod namespace"

# Scope to a namespace / context
uv run devops-agent triage -n prod --context eks-prod "checkout latency spiked at 14:05"

# Network reachability question
uv run devops-agent triage "the app says it can't reach redis.prod.svc:6379"

# Interactive session (keeps context across turns)
uv run devops-agent chat -n prod

# What can it do? / Is my environment wired up?
uv run devops-agent tools
uv run devops-agent doctor
```

The agent prints the tools it called, then a triage report: summary, evidence,
likely root cause, recommended actions, and open questions.

## Run as a GitHub Copilot agent (hosted on AWS / Bedrock)

The same triage agent can be exposed as a **GitHub Copilot agent (extension)** so
your team invokes it right inside Copilot Chat:

```
@devops-triage payments pods are CrashLoopBackOff in prod
```

GitHub forwards the chat to an HTTPS endpoint; this app verifies the request
signature (ECDSA P-256, against `api.github.com/meta/public_keys/copilot_api`),
runs the agent, and streams the answer back in Copilot's OpenAI-compatible SSE
format.

```bash
uv sync --extra server
uv run devops-agent serve --no-verify        # local dev (skips signature check)
# then POST a Copilot-shaped payload to http://localhost:8000/agent
```

**Host it entirely in AWS** with Claude on **Amazon Bedrock** — no Anthropic key
leaves your account:

```bash
uv sync --extra server --extra bedrock
export DEVOPS_AGENT_LLM_PROVIDER=bedrock
export DEVOPS_AGENT_MODEL=us.anthropic.claude-opus-4-8   # a Bedrock inference profile
uv run devops-agent serve
```

A [`Dockerfile`](Dockerfile) (bundles kubectl/helm/aws) and a step-by-step
[AWS + Bedrock deployment guide](deploy/aws.md) (App Runner / ECS Fargate, IAM,
Copilot app registration) are included.

## Safety

- **Read-only by default.** Mutating verbs (`apply`, `delete`, `scale`,
  `rollout` (except status/history), `restart`, `drain`, `exec`, helm
  `upgrade`/`rollback`, EC2 `terminate`/`stop`, ...) are refused unless
  `DEVOPS_AGENT_ALLOW_MUTATIONS=true` (or `--allow-mutations`). The agent
  recommends the command for a human instead.
- **Secret redaction.** Output is scrubbed for password/token/key patterns,
  AWS keys, and JWTs before it reaches the model or the transcript. Dumping raw
  `Secret` values is refused outright.
- **Bounded commands.** Every shell command runs as an argv list (no shell
  string), with a timeout, and output is truncated to a configurable size.
- **Constrained exec.** Service tools that need `kubectl exec` only ever run
  fixed read-only client commands (never a free-form shell string), gated by
  `DEVOPS_AGENT_ALLOW_EXEC`. Database queries are validated read-only (single
  SELECT/SHOW/EXPLAIN, no DML/DDL or stacked statements; Postgres also runs in a
  read-only transaction).

## Tools available today

| Domain | Tools |
|---|---|
| **Correlation** | `incident_snapshot` (cross-source: what's firing + what changed), `cluster_health_overview` |
| **Kubernetes** | pods, describe, logs (incl. `previous`), events, top pods/nodes, get nodes, get resource (Secret-safe), rollout status |
| **Helm** | list, status, history, get values, get manifest |
| **Network** | DNS lookup, TCP check, HTTP check, ping, traceroute |
| **In-cluster network** | service endpoints, NetworkPolicies (list/describe), ingress, in-pod DNS + TCP probes |
| **Prometheus** | instant query, range query, alerts, scrape targets, label values |
| **Grafana** | health, search dashboards, list datasources, firing alerts |
| **Datadog** | metric query, logs search, monitors, events |
| **AWS** | EC2 describe instances / status / security groups, EKS clusters / describe cluster / nodegroups, CloudWatch alarms |
| **Jenkins (CI/CD)** | job status, build console log, pipeline stages, test report, queue, list jobs |
| **Kafka** | list/describe topics, list consumer groups, consumer-group lag |
| **Redis** | INFO (by section), slowlog, client list |
| **Databases** | connection check, read-only query, Postgres `pg_stat_activity` |

Kafka/Redis/DB tools reach the service by exec-ing a read-only client into its
pod. Remaining work (in-cluster network triage, correlation timeline, CI) is in
[PROGRESS.md](PROGRESS.md).

## Extending

Add a tool by writing a `@tool`-decorated function (Kubernetes and network
modules are the templates), append it to its module's `*_TOOLS` list, and
register the module in [`tools/__init__.py`](src/devops_agent/tools/__init__.py).
Anything that shells out should go through `cli_tool_output` so it inherits the
read-only guardrail, timeout, redaction, and truncation for free.
