import os
import wave
import asyncio
import logging
from livekit import rtc

logger = logging.getLogger("hr-calling-agent.participants")

class CandidateAudioRecorder:
    """Manages recording the candidate's incoming audio stream to a local wav file."""
    def __init__(self, call_id: int):
        self.call_id = call_id
        self.recording_file = f"recordings/call-{call_id}.wav"
        self.stop_recording = asyncio.Event()
        self.recording_task = None

    def start_recording(self, track: rtc.RemoteAudioTrack):
        os.makedirs("recordings", exist_ok=True)
        self.recording_task = asyncio.create_task(self._record_track(track))

    async def _record_track(self, track: rtc.RemoteAudioTrack):
        logger.info(f"Starting local audio recording for track: {track.sid}")
        audio_stream = rtc.AudioStream(track)
        wav_file = None

        try:
            async for frame_event in audio_stream:
                if self.stop_recording.is_set():
                    break

                frame = frame_event.frame
                if wav_file is None:
                    wav_file = wave.open(self.recording_file, "wb")
                    wav_file.setnchannels(frame.num_channels)
                    wav_file.setsampwidth(2)  # 16-bit PCM = 2 bytes
                    wav_file.setframerate(frame.sample_rate)
                    logger.info(
                        f"WAV File initialized: channels={frame.num_channels}, rate={frame.sample_rate}"
                    )

                wav_file.writeframes(frame.data)
        except Exception as ex:
            logger.error(f"Error during audio writing: {ex}")
        finally:
            if wav_file:
                wav_file.close()
                logger.info(f"WAV File saved to {self.recording_file}")

    async def stop(self):
        self.stop_recording.set()
        if self.recording_task:
            try:
                await self.recording_task
            except Exception as e:
                logger.error(f"Error while waiting for recording task completion: {e}")
