"""GitHub Copilot agent (extension) integration.

Exposes the DevOps triage agent as a GitHub Copilot Extension: GitHub forwards
Copilot Chat messages to an HTTP endpoint, this package verifies the request
signature, runs the LangChain agent, and streams the answer back in the
OpenAI-compatible Server-Sent Events format Copilot expects.

The agent's LLM can run on the Anthropic API or on Amazon Bedrock — so the whole
thing (Copilot agent server + model) can be hosted entirely inside AWS.
"""
