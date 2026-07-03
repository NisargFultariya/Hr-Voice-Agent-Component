import os
import json
import logging
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from hr_orchestrator.db import SessionLocal, Candidate, Campaign, Call, CallEvent
from livekit import api

logger = logging.getLogger("hr-orchestrator.dispatch")

def check_calling_hours() -> bool:
    """Checks if the current local time falls within the configured calling hours (TRAI compliance)."""
    from zoneinfo import ZoneInfo
    start_str = os.getenv("CALL_WINDOW_START", "09:00")
    end_str = os.getenv("CALL_WINDOW_END", "20:00")
    try:
        tz = ZoneInfo("Asia/Kolkata")
        now = datetime.now(tz)
    except Exception:
        now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    return start_str <= current_time_str <= end_str

async def dispatch_next_calls():
    """Checks for campaigns, fetches pending candidates under concurrency limits, and triggers dialing."""
    if not check_calling_hours():
        logger.info("Outside permitted calling hours window. Skipping dispatch loop.")
        return

    db: Session = SessionLocal()
    try:
        # Fetch running campaigns
        running_campaigns = db.query(Campaign).filter(Campaign.status == "running").all()
        if not running_campaigns:
            return

        for campaign in running_campaigns:
            # Check how many calls are currently active in this campaign
            active_calls_count = (
                db.query(Candidate)
                .filter(Candidate.campaign_id == campaign.id)
                .filter(Candidate.call_status == "calling")
                .count()
            )

            available_slots = campaign.max_concurrent_calls - active_calls_count
            if available_slots <= 0:
                logger.debug(f"Campaign '{campaign.name}' has reached its concurrency limit ({campaign.max_concurrent_calls})")
                continue

            # Fetch next pending or retry_queued candidates
            now = datetime.utcnow()
            candidates = (
                db.query(Candidate)
                .filter(Candidate.campaign_id == campaign.id)
                .filter(
                    (Candidate.call_status == "pending") |
                    ((Candidate.call_status == "retry_queued") & (Candidate.next_attempt_at <= now))
                )
                .order_by(Candidate.id.asc())
                .limit(available_slots)
                .all()
            )

            for candidate in candidates:
                # Update status immediately to prevent double picking
                candidate.call_status = "calling"
                candidate.attempt_count += 1
                candidate.next_attempt_at = None
                db.commit()

                # Trigger the call asynchronously
                asyncio.create_task(process_call(candidate.id, campaign.id))

    except Exception as e:
        logger.error(f"Error in dispatch loop: {e}")
        db.rollback()
    finally:
        db.close()

async def process_call(candidate_id: int, campaign_id: int):
    """Orchestrates room creation and SIP dial-out for a single candidate."""
    # Create thread-safe db session for the async process
    db = SessionLocal()
    call = None
    try:
        # Load candidate and campaign inside local session to prevent DetachedInstanceError
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not candidate or not campaign:
            logger.error(f"Candidate {candidate_id} or campaign {campaign_id} not found in process_call")
            return

        # Create Call record
        call = Call(
            candidate_id=candidate.id,
            campaign_id=campaign.id,
            started_at=datetime.utcnow(),
            raw_status_from_twilio="queued"
        )
        db.add(call)
        db.commit()
        db.refresh(call)

        # Log Call Event
        event = CallEvent(
            call_id=call.id,
            event_type="initiated",
            payload={"message": f"Starting call attempt {candidate.attempt_count}"}
        )
        db.add(event)
        db.commit()

        # Construct room name
        timestamp = int(datetime.utcnow().timestamp())
        room_name = f"room-cand-{candidate.id}-call-{call.id}-{timestamp}"

        # Construct metadata dictionary to pass instructions to the agent worker
        metadata_dict = {
            "call_id": call.id,
            "candidate_id": candidate.id,
            "candidate_name": candidate.name,
            "phone_number": candidate.phone_number,
            "phoneNumber": candidate.phone_number,
            "system_prompt": campaign.agent.system_prompt,
            "voice_language": campaign.agent.voice_language,
            "voice_speaker": campaign.agent.voice_speaker,
            "initial_greeting": campaign.agent.initial_greeting,
            "knowledge_context": campaign.agent.knowledge_context,
            "extra_fields": candidate.extra_fields,
            "webhook_complete": f"{os.getenv('HR_API_URL', 'http://localhost:8080')}/internal/signals/call-completed"
        }

        # Initialize LiveKit credentials
        url = os.getenv("LIVEKIT_URL", "")
        api_key = os.getenv("LIVEKIT_API_KEY", "")
        api_secret = os.getenv("LIVEKIT_API_SECRET", "")

        if not url or not api_key or not api_secret:
            logger.warning(f"[MOCK] Skipping real LiveKit room creation for room: {room_name}")
            # Mock mode: update candidate to completed after short delay
            await asyncio.sleep(5)
            cand_db = db.query(Candidate).filter(Candidate.id == candidate.id).first()
            if cand_db:
                cand_db.call_status = "completed"
                db.commit()
            call_db = db.query(Call).filter(Call.id == call.id).first()
            if call_db:
                call_db.ended_at = datetime.utcnow()
                call_db.duration_seconds = 5
                call_db.disposition = "completed"
                call_db.raw_status_from_twilio = "completed"
                db.commit()
            return

        # Dispatch agent via LiveKit SDK AgentDispatchService
        agent_name = os.getenv("LIVEKIT_AGENT_NAME", "hr-recruiter-agent")
        async with api.LiveKitAPI(url=url, api_key=api_key, api_secret=api_secret) as lkapi:
            logger.info(f"Creating LiveKit agent dispatch for agent '{agent_name}' in room: {room_name}")
            request = api.CreateAgentDispatchRequest(
                agent_name=agent_name,
                room=room_name,
                metadata=json.dumps(metadata_dict)
            )
            dispatch = await lkapi.agent_dispatch.create_dispatch(request)
            logger.info(f"Successfully created agent dispatch: {dispatch.id}")

        # Log dispatch created event
        event = CallEvent(
            call_id=call.id,
            event_type="dispatch_created",
            payload={"room_name": room_name, "dispatch_id": dispatch.id}
        )
        db.add(event)
        db.commit()

    except Exception as e:
        logger.error(f"Failed to place call to candidate {candidate.id}: {e}")
        # Mark candidate retry/failed based on campaign config
        cand_db = db.query(Candidate).filter(Candidate.id == candidate.id).first()
        if cand_db:
            if cand_db.attempt_count < campaign.retry_limit:
                cand_db.call_status = "retry_queued"
                from datetime import timedelta
                cand_db.next_attempt_at = datetime.utcnow() + timedelta(minutes=campaign.retry_delay_minutes)
            else:
                cand_db.call_status = "failed"
            db.commit()

        if call:
            call_db = db.query(Call).filter(Call.id == call.id).first()
            if call_db:
                call_db.ended_at = datetime.utcnow()
                call_db.disposition = f"failed: {str(e)}"
                call_db.raw_status_from_twilio = "failed"
                db.commit()
    finally:
        db.close()
