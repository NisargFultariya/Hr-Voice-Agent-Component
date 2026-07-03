import json
import logging

logger = logging.getLogger("hr-calling-agent.metadata")

def parse_metadata(metadata_str: str) -> dict:
    """Parses JSON metadata string from LiveKit Room/Job and returns a structured dictionary."""
    if not metadata_str:
        return {}
    try:
        data = json.loads(metadata_str)
        if isinstance(data, dict):
            return data
        else:
            logger.warning("Metadata parsed is not a dictionary")
    except Exception as e:
        logger.error(f"Error parsing metadata JSON: {e}")
    return {}
