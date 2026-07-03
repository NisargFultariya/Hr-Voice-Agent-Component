import asyncio
import os
import logging
import wave
import json
from livekit import rtc
from livekit.agents import Agent, AgentSession, AutoSubscribe, JobContext, function_tool
from hr_agent.metadata import parse_metadata
from hr_agent.job_state import JobState
from hr_agent.openrouter import get_llm_instance, fallback_extract
from hr_agent.session.speech import get_vad, get_stt, get_tts
from hr_agent.dialogue.language import clean_language, clean_speaker
from hr_agent.dialogue.scripts import build_system_prompt
from hr_agent.session.participants import CandidateAudioRecorder
from hr_agent.session.pstn import bind_pstn_events, trigger_outbound_dial
from hr_agent.signal import send_completion_signal

logger = logging.getLogger("hr-calling-agent.runner")

class HRCallingAssistant(Agent):
    """Voice AI recruiting assistant agent with function calling capability."""
    def __init__(self, instructions: str, state: JobState, **kwargs):
        super().__init__(instructions=instructions, **kwargs)
        self.state = state

    @function_tool
    async def submit_call_summary(
        self,
        disposition: str,
        extracted_fields_json: str,
        reasoning: str,
    ):
        """Call this function to save the collected details from the candidate and conclude the call.

        Args:
            disposition: One of 'interested', 'not_interested', 'wrong_number', 'callback_requested', 'completed'.
            extracted_fields_json: A JSON string containing all extracted candidate fields.
            reasoning: Brief explanation of why this disposition was chosen.
        """
        self.state.submitted = True
        self.state.disposition = disposition
        self.state.reasoning = reasoning
        try:
            self.state.extracted_fields = json.loads(extracted_fields_json)
        except Exception as e:
            logger.error(f"Failed to parse extracted fields JSON: {e}")
            self.state.extracted_fields = {"raw": extracted_fields_json}
        logger.info(
            f"Summary submitted via tool calling: disposition={disposition}, fields={self.state.extracted_fields}"
        )
        return "Call summary recorded. You can now say goodbye to the candidate."

async def run_agent_session(ctx: JobContext):
    """Binds speech, VAD, LLM, TTS pipelines, handles events and logs outputs."""
    logger.info(f"Runner launching session for job: {ctx.job.id}")

    # 1. Parse Metadata
    meta_str = ctx.room.metadata or ctx.job.metadata or ""
    metadata = parse_metadata(meta_str)

    call_id = metadata.get("call_id", 0)
    candidate_name = metadata.get("candidate_name", "Candidate")
    phone_number = metadata.get("phone_number") or metadata.get("phoneNumber") or ""
    persona_desc = metadata.get("persona_description", "You are a professional HR assistant.")
    task_desc = metadata.get("task_description", "Collect availability.")
    system_prompt = metadata.get("system_prompt", "")
    initial_greeting = metadata.get("initial_greeting")
    knowledge_context = metadata.get("knowledge_context")
    
    # If system_prompt not provided, build it
    if not system_prompt:
        system_prompt = build_system_prompt(persona_desc, task_desc)

    # Append RAG knowledge base context if provided
    if knowledge_context:
        system_prompt += f"\n\n### Knowledge Base / FAQ Context:\nUse this information to answer any questions the candidate asks about the role or company:\n{knowledge_context}"

    voice_language = clean_language(metadata.get("voice_language", "en-IN"))
    voice_speaker = clean_speaker(metadata.get("voice_speaker", "priya"))
    extra_fields = metadata.get("extra_fields", {})

    # Inject candidate details into system prompt
    context_str = f"You are calling: {candidate_name} at phone number {phone_number}.\n"
    if extra_fields:
        context_str += "Candidate Context (information you already know):\n"
        for k, v in extra_fields.items():
            context_str += f"- {k}: {v}\n"

    full_system_prompt = f"{context_str}\n\n{system_prompt}"

    # 2. Connect to Room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info("Connected to LiveKit room")

    # Trigger outbound SIP dial-out
    if phone_number:
        await trigger_outbound_dial(ctx, phone_number)

    # 3. Setup VAD, STT, LLM, TTS
    vad = get_vad()
    stt = get_stt(voice_language)
    llm = get_llm_instance()
    tts = get_tts(voice_language, voice_speaker)

    # 4. Initialize JobState and Agent
    state = JobState()
    hr_agent = HRCallingAssistant(instructions=full_system_prompt, state=state)

    # 5. Create Session
    session = AgentSession(
        vad=vad,
        stt=stt,
        llm=llm,
        tts=tts,
    )

    # 6. Audio Recorder setup
    recorder = CandidateAudioRecorder(call_id)

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if track.kind == rtc.TrackKind.KIND_AUDIO and isinstance(track, rtc.RemoteAudioTrack):
            recorder.start_recording(track)

    # 7. Bind PSTN disconnect events
    call_ended = asyncio.Event()
    def on_candidate_disconnect():
        call_ended.set()

    bind_pstn_events(ctx.room, on_candidate_disconnect)

    # 8. Start Session
    await session.start(room=ctx.room, agent=hr_agent)
    logger.info("AgentSession running in room")

    if initial_greeting:
        # Wait for candidate to join the room
        logger.info("Waiting for candidate participant to join the room...")
        async def wait_for_participant():
            if any(p.identity != ctx.room.local_participant.identity for p in ctx.room.remote_participants.values()):
                return
            
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            
            @ctx.room.on("participant_connected")
            def on_p_connected(participant):
                logger.info(f"Participant connected: {participant.identity}")
                if not fut.done():
                    fut.set_result(True)
            
            try:
                await asyncio.wait_for(fut, timeout=60.0)
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for candidate participant to join. Proceeding anyway.")

        await wait_for_participant()

        logger.info(f"Speaking initial greeting: {initial_greeting}")
        await asyncio.sleep(1.5)
        session.say(initial_greeting)

    # 9. Watch Tool Submission
    async def watch_tool_submission():
        while not state.submitted and not call_ended.is_set():
            await asyncio.sleep(0.5)
        if state.submitted:
            logger.info("Tool submission detected. Letting TTS clear and closing call...")
            await asyncio.sleep(4.0)
            call_ended.set()

    watcher_task = asyncio.create_task(watch_tool_submission())

    # Wait for call completion event
    await call_ended.wait()
    logger.info("Call ended. Compiling results...")

    # Stop recording
    await recorder.stop()

    # Cancel watcher if running
    watcher_task.cancel()

    # 10. Extract Transcript
    transcript = []
    has_history = False
    try:
        for msg in session.history.messages():
            if msg.role in ["assistant", "user"]:
                text = ""
                if isinstance(msg.content, str):
                    text = msg.content
                elif isinstance(msg.content, list):
                    text = " ".join([chunk.text for chunk in msg.content if hasattr(chunk, "text")])

                if text.strip() != "":
                    has_history = True
                    transcript.append({"role": msg.role, "text": text})
    except Exception as e:
        logger.error(f"Error parsing transcripts: {e}")

    # 11. Fallback Extraction if hung up early
    if not state.submitted and has_history:
        logger.info("Candidate hung up before tool submission. Running fallback LLM extraction.")
        transcript_str = "\n".join([f"{t['role']}: {t['text']}" for t in transcript])
        fallback_res = fallback_extract(transcript_str, system_prompt)
        state.disposition = fallback_res.get("disposition", "completed")
        state.extracted_fields = fallback_res.get("extracted_fields", {})

    # Calculate wave duration
    duration = 0
    if os.path.exists(recorder.recording_file):
        try:
            with wave.open(recorder.recording_file, "r") as w:
                duration = int(w.getnframes() / float(w.getframerate()))
        except Exception as e:
            logger.error(f"Error reading wave duration: {e}")

    # 12. Send webhook signal
    payload = {
        "call_id": call_id,
        "room_name": ctx.room.name,
        "transcript": transcript,
        "extracted_fields": state.extracted_fields,
        "disposition": state.disposition,
        "duration_seconds": duration,
        "recording_file": os.path.abspath(recorder.recording_file) if os.path.exists(recorder.recording_file) else "",
    }

    send_completion_signal(payload)

    # Disconnect room
    await ctx.room.disconnect()
    logger.info("Session closed successfully.")
