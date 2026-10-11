from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import START, StateGraph,END
from langgraph.prebuilt import tools_condition
from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace


from langchain_tavily import TavilySearch


from dotenv import load_dotenv

load_dotenv()


from langgraph.errors import GraphRecursionError


from time import sleep
from langchain_core.messages import ToolMessage

from system_prompt import SYSTEM_PROMPT




from datetime import datetime, timezone
from langchain_core.messages import SystemMessage




from time import perf_counter
from rich.console import Console
from rich.markdown import Markdown

console = Console()

from tools import   get_current_datetime



from langchain_google_genai import ChatGoogleGenerativeAI

import os

# Generate the chat interface, including the tools
chat = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    google_api_key=os.environ["GEMINI_API_KEY"]
)



# Execution budgets — initial values for testing
MAX_TOOL_ROUNDS = 5
MAX_TOOL_CALLS = 8
MAX_SEARCH_CALLS = 6
RECURSION_LIMIT = 25






# Initialize the web search tool
search_tool = TavilySearch(
    max_results=5,
    topic="general",
    search_depth="basic",
    include_answer=False,
    include_raw_content=False,
)


tools = [search_tool,get_current_datetime]
chat_with_tools = chat.bind_tools(tools)

# Generate the AgentState and Agent graph

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    tool_rounds: int
    tool_calls_used: int
    search_calls_used: int
    budget_exhausted: bool


def assistant(state: AgentState):
    current_utc = datetime.now(timezone.utc).isoformat()

    system_message = SystemMessage(
        content=(
            SYSTEM_PROMPT
            + f"\n\nCurrent UTC date and time: {current_utc}"
        )
    )

    messages = [system_message] + state["messages"]

    return {
        "messages": [
            chat_with_tools.invoke(messages)
        ]
    }





def check_tool_budget(state: AgentState):
    """Approve a batch of tool calls only if it fits all budgets."""

    messages = state["messages"]
    last_message = messages[-1]
    tool_calls = getattr(last_message, "tool_calls", [])

    # No tool calls requested: let the graph finish normally.
    if not tool_calls:
        return {"budget_exhausted": False}

    # Calculate projected usage before executing anything.
    next_round = state.get("tool_rounds", 0) + 1
    next_tool_calls = (
        state.get("tool_calls_used", 0) + len(tool_calls)
    )
    next_search_calls = (
        state.get("search_calls_used", 0)
        + sum(
            1 for call in tool_calls
            if call.get("name") == search_tool.name
        )
    )

    reasons = []

    if next_round > MAX_TOOL_ROUNDS:
        reasons.append("assistant/tool round limit")

    if next_tool_calls > MAX_TOOL_CALLS:
        reasons.append("total tool-call limit")

    if next_search_calls > MAX_SEARCH_CALLS:
        reasons.append("web-search limit")

    # Reject the entire batch if any budget would be exceeded.
    if reasons:
        console.print(
            "[bold yellow]TOOL BUDGET EXHAUSTED[/bold yellow] "
            + ", ".join(reasons)
        )
        return {"budget_exhausted": True}

    # Approve and account for the complete batch.
    console.print(
        f"[cyan]BUDGET APPROVED[/cyan] "
        f"rounds={next_round}/{MAX_TOOL_ROUNDS}, "
        f"tool calls={next_tool_calls}/{MAX_TOOL_CALLS}, "
        f"searches={next_search_calls}/{MAX_SEARCH_CALLS}"
    )

    return {
        "tool_rounds": next_round,
        "tool_calls_used": next_tool_calls,
        "search_calls_used": next_search_calls,
        "budget_exhausted": False,
    }






def finalize_without_tools(state: AgentState):
    """Produce a final answer without allowing further tool calls."""

    messages = list(state["messages"])

    # The latest assistant message requested tools that were
    # rejected by the budget checker and were never executed.
    if messages and getattr(messages[-1], "tool_calls", []):
        messages = messages[:-1]

    finalization_prompt = SystemMessage(
        content=(
            SYSTEM_PROMPT
            + "\n\nFINALIZATION MODE\n"
            "Tool execution has stopped because an execution budget "
            "was reached. You cannot use tools in this step.\n"
            "Answer the user's original question using only the "
            "available conversation and tool results.\n"
            "Do not claim that unexecuted tools succeeded.\n"
            "If essential information is missing, acknowledge "
            "the uncertainty instead of inventing facts.\n"
            "Return the best concise answer possible."
        )
    )

    console.print(
        "[bold yellow]FINALIZING WITHOUT TOOLS[/bold yellow]"
    )

    response = chat.invoke([finalization_prompt] + messages)

    return {"messages": [response]}




def retry_tool_call(request, execute):
    """Retry an individual tool call without invoking Gemini again."""

    tool_name = request.tool_call["name"]
    tool_call_id = request.tool_call["id"]
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            console.print(
                f"[cyan]TOOL EXECUTION[/cyan] {tool_name} "
                f"(attempt {attempt}/{max_attempts})"
            )

            result = execute(request)

            console.print(
                f"[green]TOOL SUCCEEDED[/green] {tool_name}"
            )
            return result

        except Exception as error:
            console.print(
                f"[yellow]TOOL FAILED[/yellow] {tool_name}: "
                f"{type(error).__name__}: {error}",
                markup=False,
            )

            if attempt == max_attempts:
                console.print(
                    f"[red]RETRIES EXHAUSTED[/red] {tool_name}"
                )

                return ToolMessage(
                    content=(
                        f"Tool '{tool_name}' failed after "
                        f"{max_attempts} attempts. "
                        f"Error type: {type(error).__name__}. "
                        "Do not invent a result. If appropriate, "
                        "try another available approach or explain "
                        "that the information could not be retrieved."
                    ),
                    name=tool_name,
                    tool_call_id=tool_call_id,
                    status="error",
                )

            # Brief backoff: wait 1 second, then 2 seconds.
            sleep(attempt)







# Graph construction
builder = StateGraph(AgentState)

builder.add_node("assistant", assistant)
builder.add_node("budget_check", check_tool_budget)
builder.add_node("tools", ToolNode(
    tools,
    wrap_tool_call=retry_tool_call,
))
builder.add_node("finalize", finalize_without_tools)


def route_after_assistant(state: AgentState):
    """Check whether the assistant requested any tools."""

    last_message = state["messages"][-1]

    if getattr(last_message, "tool_calls", []):
        return "budget_check"

    return END


def route_after_budget(state: AgentState):
    """Choose whether to execute tools or finalize."""

    if state.get("budget_exhausted", False):
        return "finalize"

    return "tools"


builder.add_edge(START, "assistant")

builder.add_conditional_edges(
    "assistant",
    route_after_assistant,
)

builder.add_conditional_edges(
    "budget_check",
    route_after_budget,
)

builder.add_edge("tools", "assistant")
builder.add_edge("finalize", END)

alfred = builder.compile()






 


def print_response(response):
    final_message = response["messages"][-1]

    console.print("\n🎩 [bold cyan]LUNEX[/bold cyan]")
    console.print("─" * 50)

    if isinstance(final_message.content, str):
        console.print(Markdown(final_message.content))
    else:
        console.print(str(final_message.content))

    console.print("─" * 50)



# response = alfred.invoke({"messages": "Tell me about 'Lady Ada Lovelace'"})




# print("🎩 Alfred's Response:")
# print(response["messages"][-1].content_blocks)








print()


def extract_text(content):
    """Convert Gemini's content blocks into plain text."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []

        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))

        return "\n".join(part for part in parts if part)

    return str(content)






def run_agent(question: str):
    console.rule("[bold cyan]LUNEX — NEW RUN[/bold cyan]")
    console.print(f"[bold]Question:[/bold] {question}")

    start_time = perf_counter()
    
    inputs = {
        "messages": [HumanMessage(content=question)],
        "tool_rounds": 0,
        "tool_calls_used": 0,
        "search_calls_used": 0,
        "budget_exhausted": False,
    }

    final_answer = ""

    try:
        for event in alfred.stream(inputs,stream_mode="updates",config={"recursion_limit": RECURSION_LIMIT},):
            for node_name, update in event.items():
                messages = update.get("messages", [])

                if not messages:
                    continue

                # The assistant either requests a tool or returns an answer.
                if node_name in ("assistant", "finalize"):
                    message = messages[-1]
                    tool_calls = getattr(message, "tool_calls", [])

                    if tool_calls:
                        console.print(
                            "\n[bold yellow]TOOL CALL REQUESTED[/bold yellow]"
                        )

                        for call in tool_calls:
                            console.print(
                                f"Tool: {call.get('name')}"
                            )
                            console.print(
                                f"Arguments: {call.get('args')}",
                                markup=False,
                            )
                    else:
                        
                        content = extract_text(message.content)

                        if content:
                            final_answer = content

                            console.print(
                                "\n[bold green]FINAL ANSWER[/bold green]"
                            )
                            console.print(Markdown(content))


                # ToolNode returns messages containing tool results.
                elif node_name == "tools":
                    for message in messages:
                        tool_name = getattr(
                            message, "name", "unknown tool"
                        )

                        console.print(
                            f"\n[bold cyan]TOOL RESULT — "
                            f"{tool_name}[/bold cyan]"
                        )

                        content = message.content

                        if isinstance(content, str):
                            console.print(
                                content[:5000],
                                markup=False,
                            )
                        else:
                            console.print(
                                str(content)[:5000],
                                markup=False,
                            )

        
        
        elapsed = perf_counter() - start_time
        console.print(
            f"\n[bold green]RUN COMPLETED[/bold green] "
            f"({elapsed:.2f}s)"
        )


        return final_answer

    except Exception as error:
        elapsed = perf_counter() - start_time

        console.print(
            f"\n[bold red]RUN FAILED[/bold red] "
            f"after {elapsed:.2f}s"
        )
        console.print(str(error), markup=False)
        raise



# run_agent("What's the weather like in Paris tonight? Will it be suitable for our fireworks display?")

# run_agent("Find the latest official release announcement for Python. Give the release version, announcement date, and source URL. If you cannot verify these, say so.")


if __name__ == "__main__":
    run_agent(
        "Find the latest official release version for Python"
    )












# response = alfred.invoke({"messages": "One of our guests is from Qwen. What can you tell me about their most popular model?"})

# print("🎩 Alfred's Response:")
# print(response["messages"][-1].content_blocks)



# print()


# response = alfred.invoke({"messages":"I need to speak with 'Dr. Nikola Tesla' about recent advancements in wireless energy. Can you help me prepare for this conversation?"})

# print("🎩 Alfred's Response:")
# print(response["messages"][-1].content_blocks)






