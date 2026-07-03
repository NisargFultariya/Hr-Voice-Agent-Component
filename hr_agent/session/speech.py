import os
import logging
from livekit.plugins import sarvam, silero
from hr_agent import config

logger = logging.getLogger("hr-calling-agent.speech")

def get_vad():
    """Loads and returns Silero Voice Activity Detection model."""
    logger.info("Loading Silero VAD model")
    return silero.VAD.load()

def get_stt(language: str):
    """Initializes and returns Sarvam STT (saaras) plugin."""
    api_key = config.SARVAM_API_KEY or os.getenv("SARVAM_API_KEY")
    logger.info(f"Initializing Sarvam STT for language: {language}")
    return sarvam.STT(language=language, api_key=api_key)

def get_tts(language: str, speaker: str):
    """Initializes and returns Sarvam TTS (bulbul:v3) plugin."""
    api_key = config.SARVAM_API_KEY or os.getenv("SARVAM_API_KEY")
    logger.info(f"Initializing Sarvam TTS bulbul:v3 speaker={speaker} lang={language}")
    return sarvam.TTS(
        model="bulbul:v3",
        target_language_code=language,
        speaker=speaker,
        api_key=api_key,
    )
