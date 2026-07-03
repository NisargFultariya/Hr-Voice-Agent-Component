from hr_agent.dialogue.language import clean_speaker, clean_language
from hr_agent.dialogue.scripts import build_system_prompt
from hr_agent.dialogue.scenario_planner import get_scenario_instructions

def test_clean_speaker():
    assert clean_speaker("priya") == "priya"
    assert clean_speaker("invalid_speaker") == "priya"
    assert clean_speaker(None) == "priya"

def test_clean_language():
    assert clean_language("hi-IN") == "hi-IN"
    assert clean_language(None) == "en-IN"

def test_build_system_prompt():
    prompt = build_system_prompt("Friendly HR", "Ask availability")
    assert "Friendly HR" in prompt
    assert "Ask availability" in prompt

def test_get_scenario_instructions():
    assert "availability" in get_scenario_instructions("interview_scheduling").lower()
