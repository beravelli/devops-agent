"""Builds the LangChain tool-calling triage agent."""

from __future__ import annotations

from dataclasses import dataclass

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

from .config import Settings, get_settings
from .llm import build_llm
from .prompts import SYSTEM_PROMPT
from .tools import all_tools, tools_for


@dataclass
class TriageResult:
    output: str
    steps: list[tuple]  # (AgentAction, observation) pairs

    def to_dict(self) -> dict:
        """JSON-serializable form: the report plus the tool-call trace."""
        return {
            "report": self.output,
            "steps": [
                {
                    "tool": getattr(action, "tool", None),
                    "input": getattr(action, "tool_input", None),
                    "observation": str(observation),
                }
                for action, observation in self.steps
            ],
        }


def build_agent(
    settings: Settings | None = None,
    tools: list[BaseTool] | None = None,
) -> AgentExecutor:
    settings = settings or get_settings()
    if tools is None:
        groups = settings.selected_groups()
        tools = tools_for(groups) if groups else all_tools()
    llm = build_llm(settings)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=settings.verbose,
        max_iterations=settings.max_iterations,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


def triage(query: str, settings: Settings | None = None) -> TriageResult:
    """Run a single triage request and return the report plus the tool trace."""
    executor = build_agent(settings)
    result = executor.invoke({"input": query})
    return TriageResult(
        output=result.get("output", ""),
        steps=result.get("intermediate_steps", []),
    )
