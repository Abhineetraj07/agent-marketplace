"""
Builds enhanced LangGraph agents that include marketplace tools
(list_marketplace_agents, ask_agent) alongside their original tools.
"""

import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from marketplace.agent_tools import MARKETPLACE_TOOLS, MARKETPLACE_TOOL_MAP

MARKETPLACE_INSTRUCTIONS = """

COLLABORATION WITH OTHER AGENTS:
You have access to a marketplace of AI agents. When a user asks about something
outside your expertise, you MUST collaborate with other agents. Do NOT say
"would you like me to ask another agent?" — just do it immediately.

Rules:
1. If the question is outside your database/domain, call `list_marketplace_agents` to find who can help
2. Then IMMEDIATELY call `ask_agent(agent_id, question)` to get the answer — do NOT ask the user for permission first
3. Present the response from the other agent to the user, mentioning which agent helped
4. NEVER try to answer questions using your own database when the topic belongs to another agent's domain
5. Do NOT use your own tools (list_tables, get_schema, execute_sql) for topics outside your domain

Examples:
- You are a music agent and user asks about movies → call ask_agent("filmbot", "...")
- You are a movie agent and user asks about music → call ask_agent("melody", "...")"""


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    token_usage: Annotated[list, operator.add]


def build_enhanced_agent(
    original_tools: list,
    original_tool_map: dict,
    system_prompt: str,
    model: str = "qwen2.5:7b",
    temperature: float = 0.0,
    self_agent_id: str = None,
):
    """Build a LangGraph agent with original tools + marketplace tools.

    Args:
        original_tools: List of @tool functions from the original agent
        original_tool_map: Dict mapping tool names to functions
        system_prompt: The agent's system prompt
        model: Ollama model name
        temperature: LLM temperature
        self_agent_id: This agent's ID (to avoid calling itself)
    """
    # Combine tools
    all_tools = original_tools + MARKETPLACE_TOOLS
    all_tool_map = {**original_tool_map, **MARKETPLACE_TOOL_MAP}

    # Enhance system prompt
    enhanced_prompt = system_prompt + MARKETPLACE_INSTRUCTIONS

    # Create LLM with all tools bound
    llm = ChatOllama(model=model, temperature=temperature).bind_tools(all_tools)

    def llm_node(state: AgentState) -> dict:
        messages = [SystemMessage(content=enhanced_prompt)] + state["messages"]
        response = llm.invoke(messages)

        token_entry = {"prompt_tokens": 0, "completion_tokens": 0}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            token_entry["prompt_tokens"] = response.usage_metadata.get("input_tokens", 0)
            token_entry["completion_tokens"] = response.usage_metadata.get("output_tokens", 0)

        return {"messages": [response], "token_usage": [token_entry]}

    def tool_node(state: AgentState) -> dict:
        last_message = state["messages"][-1]
        results = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            # Prevent agent from calling itself
            if tool_name == "ask_agent" and self_agent_id and tool_args.get("agent_id") == self_agent_id:
                result = f"You cannot call yourself. Try a different agent."
            else:
                tool_fn = all_tool_map.get(tool_name)
                if tool_fn:
                    result = tool_fn.invoke(tool_args)
                else:
                    result = f"Unknown tool: {tool_name}"

            results.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

        return {"messages": results}

    def should_use_tools(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"

    graph = StateGraph(AgentState)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_use_tools, {"tools": "tools", "end": END})
    graph.add_edge("tools", "llm")

    return graph.compile()


def invoke_enhanced_agent(agent, question: str) -> dict:
    """Run a question through an enhanced agent and return metrics."""
    start_time = time.time()
    result = agent.invoke({
        "messages": [HumanMessage(content=question)],
        "token_usage": [],
    })
    latency = time.time() - start_time

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    response = ai_messages[-1].content if ai_messages else "No response"

    tool_calls = sum(1 for m in result["messages"] if isinstance(m, ToolMessage))
    prompt_tokens = sum(t["prompt_tokens"] for t in result.get("token_usage", []))
    completion_tokens = sum(t["completion_tokens"] for t in result.get("token_usage", []))

    return {
        "response": response,
        "latency": round(latency, 2),
        "tool_calls": tool_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
