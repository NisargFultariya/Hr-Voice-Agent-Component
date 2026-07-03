import logging

logger = logging.getLogger("hr-calling-agent.language")

COMPATIBLE_SPEAKERS = {
    "shubh", "ritu", "rahul", "pooja", "simran", "kavya", "amit", "ratan", "rohan", "dev",
    "ishita", "shreya", "manan", "sumit", "priya", "aditya", "kabir", "neha", "varun", "roopa",
    "aayan", "ashutosh", "advait", "amelia", "sophia", "suhani", "rupali", "tanya", "shruti", "kavitha"
}

def clean_speaker(speaker: str) -> str:
    """Validates the TTS speaker string to ensure compatibility with bulbul:v3 model."""
    if not speaker:
        return "priya"
    cleaned = speaker.lower().strip()
    if cleaned in COMPATIBLE_SPEAKERS:
        return cleaned
    logger.warning(f"Speaker '{speaker}' is incompatible with bulbul:v3. Falling back to 'priya'.")
    return "priya"

def clean_language(language: str) -> str:
    """Cleans and defaults language parameters for voice agents."""
    if not language:
        return "en-IN"
    return language.strip()
