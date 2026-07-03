import logging
from livekit.agents import WorkerOptions, cli
from hr_agent.session.runner import run_agent_session

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hr-calling-agent.entrypoint")

if __name__ == "__main__":
    logger.info("Starting LiveKit Recruiter Agent Worker")
    cli.run_app(WorkerOptions(entrypoint_fnc=run_agent_session))
