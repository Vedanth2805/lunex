from langchain_community.tools import DuckDuckGoSearchRun



from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from langchain_core.tools import tool




search_tool = DuckDuckGoSearchRun()

from langchain_core.tools import Tool
from huggingface_hub import list_models

def get_hub_stats(author: str) -> str:
    """Fetches the most downloaded model from a specific author on the Hugging Face Hub."""
    try:
        # List models from the specified author, sorted by downloads
        models = list(list_models(author=author, sort="downloads", limit=1))

        if models:
            model = models[0]
            return f"The most downloaded model by {author} is {model.id} with {model.downloads:,} downloads."
        else:
            return f"No models found for author {author}."
    except Exception as e:
        return f"Error fetching models for {author}: {str(e)}"

# Initialize the tool
hub_stats_tool = Tool(
    name="get_hub_stats",
    func=get_hub_stats,
    description="Fetches the most downloaded model from a specific author on the Hugging Face Hub."
)



# date and time tool
@tool
def get_current_datetime(timezone_name: str = "UTC") -> str:
    """Get the current date, time, and UTC offset for an IANA
    timezone, such as Europe/Paris or Asia/Kolkata.
    Use UTC if the relevant timezone is unknown."""

    try:
        now = datetime.now(ZoneInfo(timezone_name))
        return now.isoformat()

    except (ZoneInfoNotFoundError, ValueError):
        return (
            f"Unknown timezone: {timezone_name}. "
            "Use a valid IANA timezone, such as UTC or Asia/Kolkata."
        )
