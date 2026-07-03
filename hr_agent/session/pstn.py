import os
import logging
from livekit import api, rtc
from livekit.agents import JobContext

logger = logging.getLogger("hr-calling-agent.pstn")

def bind_pstn_events(room: rtc.Room, on_disconnect_callback):
    """Binds event handlers for participant disconnections, typical of PSTN hang-ups."""
    @room.on("participant_disconnected")
    def on_participant_disconnected(participant: rtc.RemoteParticipant):
        identity = participant.identity
        if identity.startswith("candidate_") or identity.startswith("mock_candidate_") or identity == "candidate":
            logger.info(f"PSTN Candidate disconnected: identity={identity}, name={participant.name}")
            on_disconnect_callback()

async def trigger_outbound_dial(ctx: JobContext, phone_number: str):
    """Triggers outbound SIP dial-out from the worker session using ctx.api."""
    sip_trunk_id = os.getenv("LIVEKIT_SIP_TRUNK_ID")
    if not sip_trunk_id:
        logger.warning("LIVEKIT_SIP_TRUNK_ID is not configured. Outbound SIP dial-out skipped.")
        return

    logger.info(f"Initiating outbound SIP call to {phone_number} via trunk {sip_trunk_id}")
    try:
        request = api.CreateSIPParticipantRequest(
            room_name=ctx.room.name,
            sip_trunk_id=sip_trunk_id,
            sip_call_to=phone_number,
            participant_identity=f"candidate_{phone_number}",
            participant_name="Candidate"
        )
        await ctx.api.sip.create_sip_participant(request)
        logger.info("Outbound SIP participant creation request sent successfully")
    except Exception as e:
        logger.error(f"Error creating SIP participant in room {ctx.room.name}: {e}")
        raise e
