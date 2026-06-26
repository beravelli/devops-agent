"""Command-line interface for the DevOps triage agent."""

from __future__ import annotations

import json
import os
import sys

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import get_settings
from .shell import run_command
from .tools import tool_groups

app = typer.Typer(
    add_completion=False,
    help="LangChain-based DevOps triage agent (CI/CD, network, Kubernetes, Helm, AWS, observability).",
)
console = Console()


def _apply_overrides(
    namespace: str | None,
    context: str | None,
    allow_mutations: bool,
    verbose: bool,
    groups: str | None = None,
) -> None:
    """Mutate the cached Settings singleton so tools pick up CLI overrides."""
    settings = get_settings()
    if namespace is not None:
        settings.kube_namespace = namespace
    if context is not None:
        settings.kube_context = context
    if allow_mutations:
        settings.allow_mutations = True
    if verbose:
        settings.verbose = True
    if groups is not None:
        settings.tool_groups = groups


def _render_steps(steps: list[tuple]) -> None:
    if not steps:
        return
    table = Table(title="Tool calls", show_lines=False, expand=True)
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Tool", style="magenta", no_wrap=True)
    table.add_column("Input", overflow="fold")
    for i, (action, _obs) in enumerate(steps, 1):
        tool_name = getattr(action, "tool", "?")
        tool_input = getattr(action, "tool_input", "")
        table.add_row(str(i), str(tool_name), str(tool_input))
    console.print(table)


@app.command()
def triage(
    query: str = typer.Argument(..., help="Incident description / question. Use '-' to read from stdin."),
    namespace: str = typer.Option(None, "--namespace", "-n", help="Default Kubernetes namespace."),
    context: str = typer.Option(None, "--context", help="Kubernetes context."),
    allow_mutations: bool = typer.Option(False, "--allow-mutations", help="Permit state-changing commands."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Stream the agent's tool calls."),
    show_steps: bool = typer.Option(True, "--show-steps/--no-show-steps", help="Print the tool-call trace."),
    groups: str = typer.Option(None, "--groups", help="Limit to tool groups, e.g. 'kubernetes,helm,prometheus'."),
    output: str = typer.Option("text", "--output", "-o", help="Output format: text or json."),
) -> None:
    """Run a one-shot triage and print a report."""
    if query == "-":
        query = sys.stdin.read().strip()
    if not query:
        console.print("[red]No query provided.[/red]")
        raise typer.Exit(2)

    _apply_overrides(namespace, context, allow_mutations, verbose, groups)

    from .agent import triage as run_triage  # deferred import: avoids LLM import on --help

    quiet = output == "json"
    try:
        if quiet:
            result = run_triage(query)
        else:
            with console.status("[bold green]Triaging…", spinner="dots"):
                result = run_triage(query)
    except Exception as exc:  # surface config/credential errors cleanly
        if quiet:
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        else:
            console.print(Panel(f"[red]{type(exc).__name__}: {exc}[/red]", title="Triage failed"))
        raise typer.Exit(1)

    if quiet:
        print(json.dumps({"query": query, **result.to_dict()}, indent=2))
        return
    if show_steps:
        _render_steps(result.steps)
    console.print(Panel(Markdown(result.output or "(no output)"), title="Triage report", border_style="green"))


@app.command()
def chat(
    namespace: str = typer.Option(None, "--namespace", "-n"),
    context: str = typer.Option(None, "--context"),
    allow_mutations: bool = typer.Option(False, "--allow-mutations"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    groups: str = typer.Option(None, "--groups", help="Limit to tool groups."),
) -> None:
    """Interactive multi-turn triage session. Ctrl-D or 'exit' to quit."""
    _apply_overrides(namespace, context, allow_mutations, verbose, groups)

    from langchain_core.messages import AIMessage, HumanMessage

    from .agent import build_agent

    executor = build_agent()
    history: list = []
    console.print("[bold]DevOps triage chat.[/bold] Type your question; 'exit' to quit.\n")
    while True:
        try:
            user = console.input("[bold cyan]you ›[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye.")
            break
        if user.lower() in {"exit", "quit"}:
            break
        if not user:
            continue
        with console.status("[bold green]Thinking…", spinner="dots"):
            result = executor.invoke({"input": user, "chat_history": history})
        output = result.get("output", "")
        console.print(Panel(Markdown(output or "(no output)"), border_style="green"))
        history.append(HumanMessage(content=user))
        history.append(AIMessage(content=output))


@app.command()
def tools() -> None:
    """List the tools the agent can call, grouped by domain."""
    groups = tool_groups()
    total = sum(len(v) for v in groups.values())
    console.print(f"[bold]{total} tools across {len(groups)} domains[/bold]\n")
    for name, group in groups.items():
        table = Table(title=name, show_header=True, header_style="bold magenta", expand=True)
        table.add_column("Tool", style="cyan", no_wrap=True)
        table.add_column("Description", overflow="fold")
        for t in group:
            summary = (t.description or "").strip().splitlines()[0]
            table.add_row(t.name, summary)
        console.print(table)


@app.command()
def doctor() -> None:
    """Check which CLIs are installed and which backends are configured."""
    settings = get_settings()

    bin_table = Table(title="CLIs", show_header=True, header_style="bold")
    bin_table.add_column("Tool")
    bin_table.add_column("Status")
    for binary in ["kubectl", "helm", "aws", "ping", "traceroute"]:
        res = run_command([binary, "version"] if binary in {"kubectl", "helm", "aws"} else [binary, "-V"], timeout=10)
        present = res.returncode != 127
        bin_table.add_row(binary, "[green]found[/green]" if present else "[yellow]missing[/yellow]")
    console.print(bin_table)

    cfg_table = Table(title="Backends", show_header=True, header_style="bold")
    cfg_table.add_column("Backend")
    cfg_table.add_column("Configured")
    llm_ok = (
        (settings.llm_provider == "anthropic" and bool(os.environ.get("ANTHROPIC_API_KEY")))
        or settings.llm_provider == "bedrock"
        or (settings.llm_provider == "github" and bool(settings.github_token))
    )
    checks = {
        f"LLM ({settings.llm_provider})": llm_ok,
        "Prometheus": bool(settings.prometheus_url),
        "Grafana": bool(settings.grafana_url),
        "Datadog": bool(settings.datadog_api_key and settings.datadog_app_key),
        "Jenkins": bool(settings.jenkins_url),
    }
    for name, ok in checks.items():
        cfg_table.add_row(name, "[green]yes[/green]" if ok else "[dim]no[/dim]")
    console.print(cfg_table)
    console.print(
        f"\nProvider: [bold]{settings.llm_provider}[/bold]  Model: [bold]{settings.model}[/bold]  "
        f"Mutations allowed: [bold]{settings.allow_mutations}[/bold]"
    )


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int = typer.Option(8000, help="Bind port."),
    namespace: str = typer.Option(None, "--namespace", "-n", help="Default Kubernetes namespace."),
    context: str = typer.Option(None, "--context", help="Kubernetes context."),
    allow_mutations: bool = typer.Option(False, "--allow-mutations", help="Permit state-changing commands."),
    no_verify: bool = typer.Option(
        False, "--no-verify", help="Disable GitHub signature verification (LOCAL TESTING ONLY)."
    ),
) -> None:
    """Run the GitHub Copilot agent HTTP server (also deployable to AWS)."""
    _apply_overrides(namespace, context, allow_mutations, verbose=False)
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]The server extra is not installed.[/red] Run: [bold]uv sync --extra server[/bold]"
        )
        raise typer.Exit(1)

    from .copilot.server import create_app

    if no_verify:
        console.print("[yellow]WARNING: signature verification disabled — local testing only.[/yellow]")
    application = create_app(verify_signatures=not no_verify)
    console.print(f"[green]Serving Copilot agent on http://{host}:{port}/agent[/green]")
    uvicorn.run(application, host=host, port=port)


@app.command("run-tool")
def run_tool(
    name: str = typer.Argument(..., help="Tool name, e.g. k8s_get_pods"),
    input_json: str = typer.Argument("{}", help="JSON-encoded tool input, e.g. '{\"all_namespaces\":true}'"),
) -> None:
    """Call a single tool by name and print its output as plain text.

    Used by the VS Code Chat Participant extension to execute individual tools
    while letting Copilot's own model handle the reasoning loop.
    """
    from .tools import all_tools

    tool_map = {t.name: t for t in all_tools()}
    if name not in tool_map:
        console.print(f"[red]Unknown tool: {name!r}[/red]")
        console.print(f"Known tools: {', '.join(sorted(tool_map))}")
        raise typer.Exit(1)
    try:
        parsed = json.loads(input_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON input: {exc}[/red]")
        raise typer.Exit(1)
    result = tool_map[name].invoke(parsed)
    print(result)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"devops-agent {__version__}")


if __name__ == "__main__":
    app()
