from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import tools_condition
from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace


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

from tools import DuckDuckGoSearchRun, hub_stats_tool , get_current_datetime



from langchain_google_genai import ChatGoogleGenerativeAI

import os

# Generate the chat interface, including the tools
chat = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    google_api_key=os.environ["GEMINI_API_KEY"]
)



# Initialize the web search tool
search_tool = DuckDuckGoSearchRun()


tools = [search_tool, hub_stats_tool,get_current_datetime]
chat_with_tools = chat.bind_tools(tools)

# Generate the AgentState and Agent graph
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

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






## The graph
builder = StateGraph(AgentState)

# Define nodes: these do the work
builder.add_node("assistant", assistant)
tool_node = ToolNode(
    tools,
    wrap_tool_call=retry_tool_call,
)

builder.add_node("tools", tool_node)

# Define edges: these determine how the control flow moves
builder.add_edge(START, "assistant")
builder.add_conditional_edges(
    "assistant",
    # If the latest message requires a tool, route to tools
    # Otherwise, provide a direct response
    tools_condition,
)
builder.add_edge("tools", "assistant")
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







def run_agent(question: str):
    console.rule("[bold cyan]LUNEX — NEW RUN[/bold cyan]")
    console.print(f"[bold]Question:[/bold] {question}")

    start_time = perf_counter()
    inputs = {
        "messages": [HumanMessage(content=question)]
    }

    try:
        for event in alfred.stream(inputs, stream_mode="updates"):
            for node_name, update in event.items():
                messages = update.get("messages", [])

                if not messages:
                    continue

                # The assistant either requests a tool or returns an answer.
                if node_name == "assistant":
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
                        content = message.content

                        if content:
                            console.print(
                                "\n[bold green]FINAL ANSWER[/bold green]"
                            )

                            if isinstance(content, str):
                                console.print(Markdown(content))
                            else:
                                console.print(str(content), markup=False)

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

    except Exception as error:
        elapsed = perf_counter() - start_time

        console.print(
            f"\n[bold red]RUN FAILED[/bold red] "
            f"after {elapsed:.2f}s"
        )
        console.print(str(error), markup=False)
        raise



# run_agent("What's the weather like in Paris tonight? Will it be suitable for our fireworks display?")

run_agent("Find the latest official release announcement for Python. Give the release version, announcement date, and source URL. If you cannot verify these, say so.")










print()


# response = alfred.invoke({"messages": "One of our guests is from Qwen. What can you tell me about their most popular model?"})

# print("🎩 Alfred's Response:")
# print(response["messages"][-1].content_blocks)



# print()


# response = alfred.invoke({"messages":"I need to speak with 'Dr. Nikola Tesla' about recent advancements in wireless energy. Can you help me prepare for this conversation?"})

# print("🎩 Alfred's Response:")
# print(response["messages"][-1].content_blocks)






