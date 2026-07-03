import os
import json
import logging
import requests
from livekit.plugins import openai
from hr_agent import config

logger = logging.getLogger("hr-calling-agent.openrouter")

def get_llm_instance() -> openai.LLM:
    """Configures and returns the livekit openai.LLM instance pointing to Groq or OpenRouter."""
    if config.OPENROUTER_API_KEY:
        logger.info("Initializing OpenRouter LLM client (meta-llama/llama-3.3-70b-instruct)")
        return openai.LLM(
            model="meta-llama/llama-3.3-70b-instruct",
            base_url="https://openrouter.ai/api/v1",
            api_key=config.OPENROUTER_API_KEY,
        )
    elif config.GROQ_API_KEY:
        logger.info("Initializing Groq LLM client (llama-3.3-70b-versatile)")
        return openai.LLM(
            model="llama-3.3-70b-versatile",
            base_url="https://api.groq.com/openai/v1",
            api_key=config.GROQ_API_KEY,
        )
    else:
        logger.error("No LLM API keys configured! Please set GROQ_API_KEY or OPENROUTER_API_KEY")
        return openai.LLM(
            model="llama-3.3-70b-versatile",
            base_url="https://api.groq.com/openai/v1",
            api_key="missing_key",
        )

def fallback_extract(transcript_str: str, system_prompt: str) -> dict:
    """Invokes OpenAI Chat Completions API synchronously to extract details in case candidate hangs up early."""
    fallback_prompt = f"""You are an HR data extraction assistant.
Analyze the following transcript of a phone conversation and extract the details in JSON format as required.

Required Fields:
{system_prompt}

Transcript:
{transcript_str}

Respond with a JSON object containing two fields:
1. "disposition": one of "interested", "not_interested", "wrong_number", "callback_requested", "completed"
2. "extracted_fields": JSON object of all fields collected from the transcript.

Format:
{{
  "disposition": "...",
  "extracted_fields": {{ ... }}
}}
Do NOT output any markdown tags or text, output raw JSON only."""

    try:
        if config.GROQ_API_KEY or os.getenv("GROQ_API_KEY"):
            key = config.GROQ_API_KEY or os.getenv("GROQ_API_KEY")
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": fallback_prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body, timeout=15)
        else:
            openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
            if not openai_key:
                logger.warning("No LLM key configured for fallback extraction")
                return {"disposition": "completed", "extracted_fields": {}}
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": fallback_prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }
            res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=15)

        if res.status_code == 200:
            choice = res.json().get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            return json.loads(content)
        else:
            logger.error(f"Fallback LLM extraction failed: {res.status_code} - {res.text}")
    except Exception as e:
        logger.error(f"Exception during fallback extraction: {e}")
    return {"disposition": "completed", "extracted_fields": {}}
