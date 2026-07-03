import requests
import logging
from hr_agent import config

logger = logging.getLogger("hr-calling-agent.signal")

def send_completion_signal(payload: dict) -> bool:
    """Sends the call results payload to the hr_orchestrator API endpoint."""
    url = f"{config.HR_API_URL}/internal/signals/call-completed"
    headers = {
        "x-hr-internal-secret": config.HR_INTERNAL_SIGNAL_SECRET,
        "Content-Type": "application/json"
    }
    logger.info(f"Sending completion signal to {url} for call_id: {payload.get('call_id')}")
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            logger.info("Orchestrator successfully processed the signal")
            return True
        else:
            logger.error(f"Orchestrator returned error: {res.status_code} - {res.text}")
            return False
    except Exception as e:
        logger.error(f"Exception sending completion signal: {e}")
        return False
