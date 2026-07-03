import re
import csv
import logging
from io import StringIO
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Request, Response
from sqlalchemy.orm import Session
from hr_orchestrator.db import SessionLocal, Agent, Campaign, Candidate, Call, init_db

logger = logging.getLogger("hr-orchestrator.routes")

router = APIRouter(prefix="/api")

class AgentCreate(BaseModel):
    name: str
    persona_description: str
    task_description: str
    voice_language: Optional[str] = "en-IN"
    voice_speaker: Optional[str] = "priya"
    initial_greeting: Optional[str] = None
    knowledge_context: Optional[str] = None

class CampaignCreate(BaseModel):
    agent_id: int
    name: str
    scheduled_at: datetime
    retry_limit: Optional[int] = 1
    retry_delay_minutes: Optional[int] = 15
    max_concurrent_calls: Optional[int] = 1

class CandidateCreate(BaseModel):
    name: str
    phone_number: str
    extra_fields: Optional[Dict[str, Any]] = {}

class QuickCallCreate(BaseModel):
    name: str
    phone_number: str
    extra_fields: Optional[Dict[str, Any]] = {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def normalize_phone_number(phone: str) -> str:
    """Normalizes phone numbers to standard E.164 formatting."""
    cleaned = re.sub(r"[^0-9+]", "", phone)
    if not cleaned:
        raise ValueError("phone number is empty")

    if cleaned.startswith("+"):
        if 8 <= len(cleaned) <= 16:
            return cleaned
        raise ValueError("invalid international number length")

    if len(cleaned) == 10:
        return "+91" + cleaned
    elif len(cleaned) == 12 and cleaned.startswith("91"):
        return "+" + cleaned

    if 7 <= len(cleaned) <= 15:
        return "+" + cleaned

    raise ValueError("unable to parse or normalize number format")

def build_system_prompt(persona: str, task: str) -> str:
    """Helper to compile the system prompt template."""
    return f"""You are a professional voice AI recruiter/HR assistant.

### Persona:
{persona}

### Task:
Your main objective is to have a natural conversation and collect the following candidate details:
{task}

### Conversation Guidelines:
1. Stay in persona at all times. Be friendly, polite, conversational, and professional.
2. Introduce yourself at the start of the call. Clearly explain who you are, which company/team you represent, and why you are calling.
3. If candidate details are provided in your context, personalize your opening (e.g. "Hi [Name], calling regarding the Backend Engineer role you applied to").
4. Walk through your questions one by one. Do not ask for all details at once. Give the candidate room to speak.
5. If the candidate is busy, wrong person, or wrong number:
   - Wrong number/person: Apologize and politely conclude the call.
   - Busy: Ask when would be a better time to connect, and politely conclude.
   - Not interested: Respectfully thank them and end the call.
6. Once the conversation reaches a natural end (i.e. you have collected the details, or they want a callback, or they are not interested), you MUST invoke the "submit_call_summary" tool to record the result.
7. After calling "submit_call_summary", politely say goodbye and end the conversation. Do not ask any more questions."""

@router.post("/agents", status_code=status.HTTP_201_CREATED)
def create_agent(input_data: AgentCreate, db: Session = Depends(get_db)):
    system_prompt = build_system_prompt(input_data.persona_description, input_data.task_description)
    agent = Agent(
        name=input_data.name,
        persona_description=input_data.persona_description,
        task_description=input_data.task_description,
        voice_language=input_data.voice_language,
        voice_speaker=input_data.voice_speaker,
        system_prompt=system_prompt,
        initial_greeting=input_data.initial_greeting,
        knowledge_context=input_data.knowledge_context
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent

@router.get("/agents")
def list_agents(db: Session = Depends(get_db)):
    return db.query(Agent).order_by(Agent.id.desc()).all()

@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
def create_campaign(input_data: CampaignCreate, db: Session = Depends(get_db)):
    # Validate agent
    agent = db.query(Agent).filter(Agent.id == input_data.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    campaign = Campaign(
        agent_id=input_data.agent_id,
        name=input_data.name,
        scheduled_at=input_data.scheduled_at,
        status="draft",
        retry_limit=input_data.retry_limit,
        retry_delay_minutes=input_data.retry_delay_minutes,
        max_concurrent_calls=input_data.max_concurrent_calls
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign

@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    return db.query(Campaign).order_by(Campaign.id.desc()).all()

@router.get("/campaigns/{id}")
def get_campaign(id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    candidates = db.query(Candidate).filter(Candidate.campaign_id == id).all()
    
    # Return serializable dict
    return {
        "campaign": {
            "id": campaign.id,
            "agent_id": campaign.agent_id,
            "name": campaign.name,
            "scheduled_at": campaign.scheduled_at,
            "status": campaign.status,
            "retry_limit": campaign.retry_limit,
            "retry_delay_minutes": campaign.retry_delay_minutes,
            "max_concurrent_calls": campaign.max_concurrent_calls,
            "created_at": campaign.created_at,
            "agent": {
                "id": campaign.agent.id,
                "name": campaign.agent.name,
                "voice_language": campaign.agent.voice_language,
                "voice_speaker": campaign.agent.voice_speaker,
            }
        },
        "candidates": [
            {
                "id": c.id,
                "campaign_id": c.campaign_id,
                "name": c.name,
                "phone_number": c.phone_number,
                "extra_fields": c.extra_fields,
                "call_status": c.call_status,
                "attempt_count": c.attempt_count,
                "next_attempt_at": c.next_attempt_at,
            } for c in candidates
        ]
    }

@router.post("/campaigns/{id}/upload")
async def upload_candidates_csv(id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    contents = await file.read()
    string_data = contents.decode("utf-8")
    csv_file = StringIO(string_data)
    reader = csv.reader(csv_file)

    try:
        headers = next(reader)
    except StopIteration:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    name_idx = -1
    phone_idx = -1

    for idx, header in enumerate(headers):
        lower_header = header.lower().strip()
        if lower_header == "name":
            name_idx = idx
        elif lower_header in ["phone_number", "phone", "mobile"]:
            phone_idx = idx

    if name_idx == -1 or phone_idx == -1:
        raise HTTPException(status_code=400, detail="CSV must contain 'name' and 'phone_number' (or 'phone') columns")

    candidates = []
    row_errors = []
    row_num = 1

    for row in reader:
        row_num += 1
        if not row:
            continue
        
        if len(row) <= name_idx or len(row) <= phone_idx:
            row_errors.append(f"Row {row_num}: missing name or phone column")
            continue

        name = row[name_idx].strip()
        raw_phone = row[phone_idx].strip()

        if not name:
            row_errors.append(f"Row {row_num}: 'name' is empty")
            continue

        try:
            phone = normalize_phone_number(raw_phone)
        except ValueError as err:
            row_errors.append(f"Row {row_num}: invalid phone number '{raw_phone}' ({err})")
            continue

        # Extract extra fields
        extra = {}
        for idx, val in enumerate(row):
            if idx != name_idx and idx != phone_idx and idx < len(headers):
                key = headers[idx].strip()
                if key:
                    extra[key] = val.strip()

        candidates.append(Candidate(
            campaign_id=campaign.id,
            name=name,
            phone_number=phone,
            extra_fields=extra,
            call_status="pending"
        ))

    if row_errors:
        raise HTTPException(status_code=400, detail={"error": "CSV validation failed", "row_errors": row_errors})

    if not candidates:
        raise HTTPException(status_code=400, detail="CSV contains no valid candidate records")

    # Save candidates
    for candidate in candidates:
        db.add(candidate)
    
    # Update campaign status
    if campaign.status == "draft":
        campaign.status = "scheduled"

    db.commit()

    return {
        "message": f"Successfully imported {len(candidates)} candidates",
        "candidates_count": len(candidates)
    }

@router.post("/campaigns/{id}/candidate")
def add_single_candidate(id: int, input_data: CandidateCreate, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        phone = normalize_phone_number(input_data.phone_number)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    candidate = Candidate(
        campaign_id=campaign.id,
        name=input_data.name,
        phone_number=phone,
        extra_fields=input_data.extra_fields,
        call_status="pending"
    )
    db.add(candidate)

    if campaign.status in ["draft", "scheduled"]:
        campaign.status = "running"

    db.commit()
    db.refresh(candidate)

    return {
        "message": "Candidate added and queued for calling",
        "candidate": {
            "id": candidate.id,
            "campaign_id": candidate.campaign_id,
            "name": candidate.name,
            "phone_number": candidate.phone_number,
            "extra_fields": candidate.extra_fields,
            "call_status": candidate.call_status,
        }
    }

@router.post("/quick-call")
def quick_call(input_data: QuickCallCreate, db: Session = Depends(get_db)):
    try:
        phone = normalize_phone_number(input_data.phone_number)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    # Get or create default Agent
    agent = db.query(Agent).first()
    if not agent:
        persona = "You are Priya, a friendly talent recruiter representing Google."
        task = "Ask for notice period, location, and CTC expectation."
        system_prompt = build_system_prompt(persona, task)
        agent = Agent(
            name="Default Recruiter",
            persona_description=persona,
            task_description=task,
            voice_language="en-IN",
            voice_speaker="priya",
            system_prompt=system_prompt
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

    # Get or create default Campaign
    campaign = db.query(Campaign).filter(Campaign.agent_id == agent.id).first()
    if not campaign:
        campaign = Campaign(
            agent_id=agent.id,
            name="Default Outbound Campaign",
            scheduled_at=datetime.utcnow(),
            status="running",
            retry_limit=1,
            retry_delay_minutes=15,
            max_concurrent_calls=2
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

    if campaign.status != "running":
        campaign.status = "running"

    candidate = Candidate(
        campaign_id=campaign.id,
        name=input_data.name,
        phone_number=phone,
        extra_fields=input_data.extra_fields,
        call_status="pending"
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    return {
        "message": "Candidate added and queued for calling",
        "candidate": {
            "id": candidate.id,
            "campaign_id": candidate.campaign_id,
            "name": candidate.name,
            "phone_number": candidate.phone_number,
            "extra_fields": candidate.extra_fields,
            "call_status": candidate.call_status,
        }
    }

@router.get("/candidates/{candidate_id}/calls")
def get_call_details(candidate_id: int, db: Session = Depends(get_db)):
    call = db.query(Call).filter(Call.candidate_id == candidate_id).order_by(Call.id.desc()).first()
    if not call:
        raise HTTPException(status_code=404, detail="No calls found for this candidate")
    
    return {
        "id": call.id,
        "candidate_id": call.candidate_id,
        "campaign_id": call.campaign_id,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "duration_seconds": call.duration_seconds,
        "recording_url": call.recording_url,
        "transcript": call.transcript,
        "extracted_data": call.extracted_data,
        "disposition": call.disposition,
        "raw_status_from_twilio": call.raw_status_from_twilio,
        "created_at": call.created_at,
        "candidate": {
            "id": call.candidate.id,
            "name": call.candidate.name,
            "phone_number": call.candidate.phone_number
        }
    }

@router.get("/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    total_candidates = db.query(Candidate).count()
    completed_calls = db.query(Candidate).filter(Candidate.call_status == "completed").count()
    pending_calls = db.query(Candidate).filter((Candidate.call_status == "pending") | (Candidate.call_status == "retry_queued")).count()
    answered_calls = db.query(Call).filter(Call.disposition.isnot(None)).count()
    interested_count = db.query(Call).filter(Call.disposition == "interested").count()

    return {
        "total_candidates": total_candidates,
        "completed_calls": completed_calls,
        "pending_calls": pending_calls,
        "answered_calls": answered_calls,
        "interested_count": interested_count
    }

@router.post("/campaigns/{id}/start")
def start_campaign(id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign.status = "running"
    db.commit()
    return {"message": f"Campaign {campaign.name} is now running", "status": campaign.status}

@router.get("/candidates/{candidate_id}/playground-url")
def get_playground_url(candidate_id: int, db: Session = Depends(get_db)):
    import os
    from hr_orchestrator.db import CallEvent
    call = db.query(Call).filter(Call.candidate_id == candidate_id).order_by(Call.id.desc()).first()
    if not call:
        raise HTTPException(status_code=404, detail="No calls found for this candidate")

    # Find the room name from CallEvent
    event = db.query(CallEvent).filter(CallEvent.call_id == call.id, CallEvent.event_type == "dispatch_created").first()
    if not event:
        raise HTTPException(status_code=404, detail="Dispatch room not created yet")
    
    room_name = event.payload.get("room_name")
    if not room_name:
        raise HTTPException(status_code=404, detail="Room name not found in events")

    # Generate Access Token
    url = os.getenv("LIVEKIT_URL", "")
    api_key = os.getenv("LIVEKIT_API_KEY", "")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "")
    
    if not url or not api_key or not api_secret:
        raise HTTPException(status_code=500, detail="LiveKit credentials missing on server")

    from livekit import api
    try:
        token = (
            api.AccessToken(api_key, api_secret)
            .with_identity(f"mock_candidate_{candidate_id}")
            .with_name(call.candidate.name)
            .with_grants(api.VideoGrants(
                room_join=True,
                room=room_name
            ))
            .to_jwt()
        )
        playground_url = f"https://agents-playground.livekit.io/?url={url}&token={token}"
        return {"playground_url": playground_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate token: {e}")

@router.get("/candidates/{candidate_id}/token")
def get_candidate_token(candidate_id: int, db: Session = Depends(get_db)):
    import os
    from hr_orchestrator.db import CallEvent
    call = db.query(Call).filter(Call.candidate_id == candidate_id).order_by(Call.id.desc()).first()
    if not call:
        raise HTTPException(status_code=404, detail="No calls found for this candidate")

    # Find the room name from CallEvent
    event = db.query(CallEvent).filter(CallEvent.call_id == call.id, CallEvent.event_type == "dispatch_created").first()
    if not event:
        raise HTTPException(status_code=404, detail="Dispatch room not created yet")
    
    room_name = event.payload.get("room_name")
    if not room_name:
        raise HTTPException(status_code=404, detail="Room name not found in events")

    # Generate Access Token
    url = os.getenv("LIVEKIT_URL", "")
    api_key = os.getenv("LIVEKIT_API_KEY", "")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "")
    
    if not url or not api_key or not api_secret:
        raise HTTPException(status_code=500, detail="LiveKit credentials missing on server")

    from livekit import api
    try:
        token = (
            api.AccessToken(api_key, api_secret)
            .with_identity(f"mock_candidate_{candidate_id}")
            .with_name(call.candidate.name)
            .with_grants(api.VideoGrants(
                room_join=True,
                room=room_name
            ))
            .to_jwt()
        )
        return {"url": url, "token": token, "room_name": room_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate token: {e}")



