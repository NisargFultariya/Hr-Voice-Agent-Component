import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from hr_orchestrator.db import init_db, SessionLocal
from hr_orchestrator.routes import router as api_router
from hr_orchestrator.signals import router as signal_router
from hr_orchestrator.dispatch import dispatch_next_calls

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hr-orchestrator")

async def scheduler_loop():
    """Background polling loop executing candidate call dispatches every 5 seconds."""
    logger.info("Outbound call dispatcher thread active")
    while True:
        try:
            await dispatch_next_calls()
        except Exception as e:
            logger.error(f"Error in dispatcher background loop: {e}")
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create database tables
    logger.info("Initializing SQLite database and running migrations")
    init_db()
    
    # Ensure local folders exist
    os.makedirs("./recordings", exist_ok=True)
    os.makedirs("./data", exist_ok=True)

    # Clean up any stuck "calling" candidates from previous container sessions
    from hr_orchestrator.db import Candidate
    db = SessionLocal()
    try:
        stuck_candidates = db.query(Candidate).filter(Candidate.call_status == "calling").all()
        if stuck_candidates:
            logger.info(f"Resetting {len(stuck_candidates)} stuck calling candidates from previous sessions")
            for c in stuck_candidates:
                c.call_status = "failed"
            db.commit()
    except Exception as e:
        logger.error(f"Failed to reset stuck candidates: {e}")
        db.rollback()
    finally:
        db.close()

    # Start background scheduler
    task = asyncio.create_task(scheduler_loop())
    yield
    # Cleanup task on exit
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="HR Candidate Calling Orchestrator",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware to allow connections from local dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount recordings endpoint to serve candidate call audio logs
app.mount("/recordings", StaticFiles(directory="./recordings"), name="recordings")

# Include Routers
app.include_router(api_router)
app.include_router(signal_router)

# Mount static folder to serve our beautiful HTML calling page/dashboard
app.mount("/", StaticFiles(directory="hr_orchestrator/static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("hr_orchestrator.main:app", host="0.0.0.0", port=8080, reload=True)
