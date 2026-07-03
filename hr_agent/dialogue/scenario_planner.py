def get_scenario_instructions(call_type: str) -> str:
    """Returns custom scenario instructions based on call_type (e.g. interview_scheduling, screening)."""
    if call_type == "interview_scheduling":
        return "Objective: Check availability and propose interview time slots."
    elif call_type == "screening":
        return "Objective: Collect candidate's notice period, current location, CTC expectations, and tech stack match."
    elif call_type == "offer_confirmation":
        return "Objective: Verify if they received the offer and their timeline for signing."
    return "Objective: Standard candidate check-in."
