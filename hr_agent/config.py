import os
from dotenv import load_dotenv

load_dotenv()

LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
LIVEKIT_AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "hr-recruiter-agent")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "priya")

HR_API_URL = os.getenv("HR_API_URL", "http://localhost:8080")
HR_INTERNAL_SIGNAL_SECRET = os.getenv("HR_INTERNAL_SIGNAL_SECRET", "supersecretchangeinproduction")
