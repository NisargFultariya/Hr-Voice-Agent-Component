import os
import logging
from datetime import datetime
from typing import List, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy.orm import Session
from hr_orchestrator.db import SessionLocal, Call, Candidate, CallEvent

logger = logging.getLogger("hr-orchestrator.signals")

router = APIRouter()

class TranscriptTurn(BaseModel):
    role: str
    text: str

class CallCompletePayload(BaseModel):
    call_id: int
    room_name: str
    transcript: List[TranscriptTurn]
    extracted_fields: Dict[str, Any]
    disposition: str
    duration_seconds: int
    recording_file: str

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/internal/signals/call-completed")
async def handle_call_completed(
    payload: CallCompletePayload,
    x_hr_internal_secret: str = Header(None),
    db: Session = Depends(get_db)
):
    """Processes the final call metrics and transcript uploaded by the agent worker."""
    expected_secret = os.getenv("HR_INTERNAL_SIGNAL_SECRET", "supersecretchangeinproduction")
    if x_hr_internal_secret != expected_secret:
        logger.warning(f"Unauthorized signal request from agent: Secret mismatch. Expected: {expected_secret}")
        raise HTTPException(status_code=401, detail="Unauthorized signal secret")

    logger.info(f"Processing call complete signal for call_id={payload.call_id} disposition={payload.disposition}")

    call = db.query(Call).filter(Call.id == payload.call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call record not found")

    # Update call log
    call.ended_at = datetime.utcnow()
    call.duration_seconds = payload.duration_seconds
    call.disposition = payload.disposition
    call.transcript = [turn.model_dump() for turn in payload.transcript]
    call.extracted_data = payload.extracted_fields
    call.raw_status_from_twilio = "completed"

    if payload.recording_file:
        base_url = os.getenv("HR_API_URL", "http://localhost:8080")
        filename = os.path.basename(payload.recording_file)
        call.recording_url = f"{base_url}/recordings/{filename}"

    # Update candidate state
    candidate = db.query(Candidate).filter(Candidate.id == call.candidate_id).first()
    if candidate:
        candidate.call_status = "completed"
        db.commit()

    # Log end call event
    event = CallEvent(
        call_id=call.id,
        event_type="ended",
        payload={
            "disposition": payload.disposition,
            "duration": payload.duration_seconds,
            "recording_file": payload.recording_file
        }
    )
    db.add(event)
    db.commit()

    logger.info(f"Call {payload.call_id} state successfully finalized in DB")
    return {"message": "Call details logged successfully"}
