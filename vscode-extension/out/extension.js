"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const child_process_1 = require("child_process");
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
const PARTICIPANT_ID = 'devops-triage.agent';
const MAX_TOOL_ROUNDS = 15;
// ---------------------------------------------------------------------------
// Tool definitions — schemas passed to the Copilot model so it knows what
// it can call. Names match exactly what `devops-agent run-tool` accepts.
// ---------------------------------------------------------------------------
const TOOLS = [
    // Kubernetes
    {
        name: 'k8s_get_pods',
        description: 'List pods and their status, restarts, and node placement (kubectl get pods -o wide). Use first when triaging a workload issue.',
        inputSchema: {
            type: 'object',
            properties: {
                namespace: { type: 'string', description: 'Namespace to query. Empty = configured default.' },
                selector: { type: 'string', description: 'Label selector, e.g. "app=payments".' },
                all_namespaces: { type: 'boolean', description: 'List pods across every namespace.' },
            },
        },
    },
    {
        name: 'k8s_describe',
        description: 'Describe a Kubernetes object including events (kubectl describe). Most useful for "why won\'t this start".',
        inputSchema: {
            type: 'object',
            properties: {
                kind: { type: 'string', description: 'Resource kind: pod, deployment, statefulset, node, service, ingress, pvc.' },
                name: { type: 'string', description: 'Object name.' },
                namespace: { type: 'string', description: 'Namespace (ignored for cluster-scoped kinds).' },
            },
            required: ['kind', 'name'],
        },
    },
    {
        name: 'k8s_logs',
        description: 'Fetch logs from a pod (kubectl logs). Set previous=true for CrashLoopBackOff.',
        inputSchema: {
            type: 'object',
            properties: {
                pod: { type: 'string', description: 'Pod name.' },
                namespace: { type: 'string', description: 'Namespace.' },
                container: { type: 'string', description: 'Container name (required for multi-container pods).' },
                tail: { type: 'number', description: 'Number of trailing lines. Default 200.' },
                previous: { type: 'boolean', description: 'Read the previous crashed container logs.' },
                since: { type: 'string', description: 'Relative time window, e.g. "15m" or "1h".' },
            },
            required: ['pod'],
        },
    },
    {
        name: 'k8s_get_events',
        description: 'List recent cluster events sorted by time (kubectl get events). Shows scheduling failures, image pull errors, volume problems.',
        inputSchema: {
            type: 'object',
            properties: {
                namespace: { type: 'string', description: 'Namespace.' },
                all_namespaces: { type: 'boolean', description: 'Events across every namespace.' },
            },
        },
    },
    {
        name: 'k8s_top_pods',
        description: 'Show pod CPU/memory usage (kubectl top pods). Requires metrics-server.',
        inputSchema: {
            type: 'object',
            properties: {
                namespace: { type: 'string', description: 'Namespace.' },
                all_namespaces: { type: 'boolean', description: 'Usage across every namespace.' },
            },
        },
    },
    {
        name: 'k8s_top_nodes',
        description: 'Show node CPU/memory usage (kubectl top nodes). Use when pods are being evicted or throttled.',
        inputSchema: { type: 'object', properties: {} },
    },
    {
        name: 'k8s_get_nodes',
        description: 'List nodes with status, roles, version, and pressure conditions. Use when pods are Pending or being evicted.',
        inputSchema: { type: 'object', properties: {} },
    },
    {
        name: 'k8s_get_resource',
        description: 'Get the manifest/spec of any Kubernetes resource (kubectl get -o yaml). Use to inspect deployments, services, ingresses, HPAs, PVCs.',
        inputSchema: {
            type: 'object',
            properties: {
                kind: { type: 'string', description: 'Resource kind: deployment, service, ingress, configmap, hpa, pvc ...' },
                name: { type: 'string', description: 'Object name. Empty = list all of that kind.' },
                namespace: { type: 'string', description: 'Namespace.' },
                output: { type: 'string', description: 'Output format: yaml, json, or wide. Default yaml.' },
                selector: { type: 'string', description: 'Label selector for listing.' },
            },
            required: ['kind'],
        },
    },
    {
        name: 'k8s_rollout_status',
        description: 'Check rollout progress of a deployment, statefulset, or daemonset. Use to confirm whether a recent deploy rolled out or is stuck.',
        inputSchema: {
            type: 'object',
            properties: {
                kind: { type: 'string', description: 'deployment, statefulset, or daemonset.' },
                name: { type: 'string', description: 'Object name.' },
                namespace: { type: 'string', description: 'Namespace.' },
            },
            required: ['kind', 'name'],
        },
    },
    // Helm
    {
        name: 'helm_list',
        description: 'List Helm releases with status, chart version, and revision. Use to see what is deployed, failed, or pending-upgrade.',
        inputSchema: {
            type: 'object',
            properties: {
                namespace: { type: 'string', description: 'Namespace.' },
                all_namespaces: { type: 'boolean', description: 'All namespaces.' },
            },
        },
    },
    {
        name: 'helm_history',
        description: 'Show revision history of a Helm release. Fastest way to see what changed and when.',
        inputSchema: {
            type: 'object',
            properties: {
                release: { type: 'string', description: 'Release name.' },
                namespace: { type: 'string', description: 'Namespace.' },
                max_revisions: { type: 'number', description: 'How many revisions to show. Default 10.' },
            },
            required: ['release'],
        },
    },
    {
        name: 'helm_status',
        description: 'Show the status of a Helm release including resources and notes.',
        inputSchema: {
            type: 'object',
            properties: {
                release: { type: 'string', description: 'Release name.' },
                namespace: { type: 'string', description: 'Namespace.' },
            },
            required: ['release'],
        },
    },
    {
        name: 'helm_get_values',
        description: 'Show user-supplied values a Helm release was rendered with.',
        inputSchema: {
            type: 'object',
            properties: {
                release: { type: 'string', description: 'Release name.' },
                namespace: { type: 'string', description: 'Namespace.' },
                revision: { type: 'number', description: 'Specific revision; 0 = current.' },
            },
            required: ['release'],
        },
    },
    // Correlation / health
    {
        name: 'cluster_health_overview',
        description: 'Cross-cluster health snapshot: node status + non-Running pods + Warning events. Start here for broad "something is wrong" reports.',
        inputSchema: { type: 'object', properties: {} },
    },
    {
        name: 'incident_snapshot',
        description: 'One-shot snapshot of what is firing across all configured backends: k8s events, Prometheus alerts, Grafana alerts, Datadog monitors.',
        inputSchema: { type: 'object', properties: {} },
    },
];
// ---------------------------------------------------------------------------
// Config helpers
// ---------------------------------------------------------------------------
function getConfig() {
    const cfg = vscode.workspace.getConfiguration('devopsTriage');
    return {
        agentPath: cfg.get('agentPath', 'devops-agent'),
        projectPath: cfg.get('projectPath', ''),
    };
}
function resolveProjectPath(cfg) {
    if (cfg.projectPath) {
        return cfg.projectPath;
    }
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();
}
// ---------------------------------------------------------------------------
// Binary resolution — finds devops-agent without relying on VS Code's PATH.
//
// VS Code's extension host inherits a stripped PATH that typically excludes
// ~/.local/bin (where uv installs scripts) and ~/.cargo/bin.  Rather than
// fighting shell initialization order, we probe the known install locations
// directly and use the full path when found.
//
// Resolution order:
//   1. The configured agentPath if it is already an absolute path that exists.
//   2. Common uv / pip install locations under $HOME.
//   3. /usr/local/bin and /opt/homebrew/bin (system-wide installs).
//   4. uv binary + `uv run --project <cwd> devops-agent` as a last resort.
//   5. The configured value as-is (will likely fail with a clear error).
// ---------------------------------------------------------------------------
const HOME = process.env.HOME ?? '';
function findBinary(name) {
    const candidates = [
        path.join(HOME, '.local', 'bin', name), // uv tool install / pip --user
        path.join(HOME, '.cargo', 'bin', name), // cargo install
        '/usr/local/bin/' + name,
        '/opt/homebrew/bin/' + name, // macOS Homebrew (Apple Silicon)
        '/usr/bin/' + name,
    ];
    return candidates.find(p => fs.existsSync(p));
}
// Returns [binary, extraArgsBefore] where the full invocation is:
//   binary  extraArgsBefore...  run-tool  <name>  <json>
function resolveAgent(configured, cwd) {
    // 1. Configured value is already a full path.
    if (path.isAbsolute(configured) && fs.existsSync(configured)) {
        return [configured, []];
    }
    // 2. Probe common install locations for 'devops-agent'.
    const direct = findBinary('devops-agent');
    if (direct) {
        return [direct, []];
    }
    // 3. Fall back to `uv run --project <cwd> devops-agent`.
    const uvBin = findBinary('uv');
    if (uvBin) {
        return [uvBin, ['run', '--project', cwd, 'devops-agent']];
    }
    // 4. Nothing found — return the configured string; error will surface clearly.
    return [configured, []];
}
// ---------------------------------------------------------------------------
// Tool execution
// ---------------------------------------------------------------------------
function runTool(toolName, toolInput, cwd, agentPath) {
    return new Promise((resolve) => {
        const [bin, prefix] = resolveAgent(agentPath, cwd);
        // argv: binary  [uv-prefix...]  run-tool  <toolName>  <json>
        // JSON is a plain argv element — not passed through a shell, so no injection risk.
        const args = [...prefix, 'run-tool', toolName, JSON.stringify(toolInput ?? {})];
        const proc = (0, child_process_1.spawn)(bin, args, {
            cwd,
            env: { ...process.env },
            stdio: ['ignore', 'pipe', 'pipe'],
        });
        let out = '';
        proc.stdout.on('data', (d) => { out += d.toString(); });
        proc.stderr.on('data', (d) => { out += d.toString(); });
        proc.on('close', () => resolve(out.trim() || '(no output)'));
        proc.on('error', (err) => {
            const tried = [
                findBinary('devops-agent') ?? '(not found in common paths)',
                findBinary('uv') ? `${findBinary('uv')} run --project ${cwd} devops-agent` : '(uv not found)',
            ];
            resolve(`Tool execution error: ${err.message}\n\n` +
                `Tried:\n${tried.map(t => '  ' + t).join('\n')}\n\n` +
                `Fix: set **devopsTriage.agentPath** in VS Code settings (Cmd+,) to one of:\n` +
                `  ${HOME}/.local/bin/devops-agent\n` +
                `  ${HOME}/.local/bin/uv   (then set agentPath to the uv binary path)`);
        });
    });
}
// ---------------------------------------------------------------------------
// Agentic loop using Copilot's model
// ---------------------------------------------------------------------------
const SYSTEM_PROMPT = `You are a senior Site Reliability / DevOps engineer acting as an on-call triage assistant.
Your job is to TRIAGE: gather evidence with the tools available, correlate signals, and report a root-cause hypothesis with evidence and concrete next steps.

Operating principles:
- For broad incidents, start with cluster_health_overview or incident_snapshot to orient, then drill in.
- Work from symptom toward cause: application logs/events → workload config → platform (nodes, networking) → dependencies.
- Reach for a tool when it would settle a question. Use previous=true in k8s_logs for CrashLoopBackOff pods.
- You are READ-ONLY. Never assume a mutating command ran. Recommend exact commands for humans to run.
- Ground every claim in tool output. Do not invent data.

When you have enough to conclude, write a concise report:
- Summary: the most likely cause in 1-2 sentences.
- Evidence: specific signals tied to the tool that produced them.
- Likely root cause and confidence.
- Recommended actions: ordered, concrete. Mark state-changing steps clearly.
- Open questions: what you could not determine.`;
const COMMAND_PROMPTS = {
    pods: 'check for any pod issues across all namespaces',
    nodes: 'check node health, resource pressure, and any NotReady conditions',
    helm: 'list all helm releases and check for failed or pending upgrades',
    logs: 'fetch recent logs from any pods that are not healthy',
    health: 'give me a full cluster health overview',
};
// ---------------------------------------------------------------------------
// Extension entry point
// ---------------------------------------------------------------------------
function activate(context) {
    const handler = async (request, _chatContext, stream, token) => {
        const cfg = getConfig();
        const cwd = resolveProjectPath(cfg);
        const query = request.command
            ? (COMMAND_PROMPTS[request.command] ?? request.prompt)
            : request.prompt.trim();
        if (!query) {
            stream.markdown('Tell me what to triage, e.g.:\n\n' +
                '- `@devops-triage pods crashing in the payments namespace`\n' +
                '- `@devops-triage /health`\n');
            return;
        }
        // Check .env exists so the user gets a clear error early
        const envFile = path.join(cwd, '.env');
        if (!fs.existsSync(envFile)) {
            stream.markdown(`⚠️ No \`.env\` found at \`${cwd}\`.\n\n` +
                'Set **devopsTriage.projectPath** in VS Code settings to the devops-agent repo root.');
            return;
        }
        // Build initial messages for the Copilot model
        const messages = [
            vscode.LanguageModelChatMessage.User(SYSTEM_PROMPT),
            vscode.LanguageModelChatMessage.User(query),
        ];
        let round = 0;
        while (round++ < MAX_TOOL_ROUNDS && !token.isCancellationRequested) {
            let response;
            try {
                response = await request.model.sendRequest(messages, { tools: TOOLS }, token);
            }
            catch (err) {
                const msg = err instanceof Error ? err.message : String(err);
                stream.markdown(`\n\n**Model error:** ${msg}`);
                return;
            }
            // Collect the full response before acting — some models interleave
            // text and tool calls and we need both.
            const toolCalls = [];
            const assistantParts = [];
            for await (const part of response.stream) {
                if (part instanceof vscode.LanguageModelTextPart) {
                    if (part.value) {
                        stream.markdown(part.value);
                        assistantParts.push(part);
                    }
                }
                else if (part instanceof vscode.LanguageModelToolCallPart) {
                    toolCalls.push(part);
                    assistantParts.push(part);
                }
            }
            // No tool calls → model is done
            if (toolCalls.length === 0) {
                break;
            }
            // Add the assistant turn (with tool calls) to history
            if (assistantParts.length > 0) {
                messages.push(vscode.LanguageModelChatMessage.Assistant(assistantParts));
            }
            // Execute each tool and collect results
            const resultParts = [];
            for (const tc of toolCalls) {
                stream.markdown(`\n\n*⚙ Calling \`${tc.name}\`...*\n`);
                const output = await runTool(tc.name, tc.input, cwd, cfg.agentPath);
                // Show a collapsible code block for the raw tool output
                stream.markdown(`\`\`\`\n${output.slice(0, 3000)}${output.length > 3000 ? '\n...(truncated)' : ''}\n\`\`\`\n`);
                resultParts.push(new vscode.LanguageModelToolResultPart(tc.callId, [
                    new vscode.LanguageModelTextPart(output),
                ]));
            }
            // Add tool results as a user turn
            messages.push(vscode.LanguageModelChatMessage.User(resultParts));
        }
    };
    const participant = vscode.chat.createChatParticipant(PARTICIPANT_ID, handler);
    participant.iconPath = new vscode.ThemeIcon('pulse');
    context.subscriptions.push(participant);
}
function deactivate() { }
//# sourceMappingURL=extension.js.map