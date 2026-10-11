from langchain_community.tools import DuckDuckGoSearchRun



from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from langchain_core.tools import tool




search_tool = DuckDuckGoSearchRun()






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
