import logging

logger = logging.getLogger("hr-calling-agent.turn_planner")

class TurnPlanner:
    """Helper class to evaluate turns if custom state transitions are needed."""
    def __init__(self):
        pass

    def evaluate_turn(self, history) -> str:
        return "continue"
