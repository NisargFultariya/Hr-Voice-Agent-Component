import os
import wave
import asyncio
import logging
from livekit import rtc

logger = logging.getLogger("hr-calling-agent.participants")

class CallAudioRecorder:
    """Manages recording both candidate (incoming) and agent (outgoing) audio streams and mixing them."""
    def __init__(self, call_id: int):
        self.call_id = call_id
        self.recording_file = f"recordings/call-{call_id}.wav"
        self.candidate_file = f"recordings/call-{call_id}-candidate.wav"
        self.agent_file = f"recordings/call-{call_id}-agent.wav"
        self.stop_recording = asyncio.Event()
        self.candidate_task = None
        self.agent_task = None
        
        self.start_time = None
        self.candidate_offset = 0.0
        self.agent_offset = 0.0

    def start_candidate_recording(self, track: rtc.RemoteAudioTrack):
        os.makedirs("recordings", exist_ok=True)
        try:
            loop_time = asyncio.get_running_loop().time()
        except RuntimeError:
            loop_time = 0.0

        if self.start_time is None:
            self.start_time = loop_time
            self.candidate_offset = 0.0
        else:
            self.candidate_offset = loop_time - self.start_time
            
        self.candidate_task = asyncio.create_task(
            self._record_track(track, self.candidate_file, self.candidate_offset, "candidate")
        )

    def start_agent_recording(self, track: rtc.LocalAudioTrack):
        os.makedirs("recordings", exist_ok=True)
        try:
            loop_time = asyncio.get_running_loop().time()
        except RuntimeError:
            loop_time = 0.0

        if self.start_time is None:
            self.start_time = loop_time
            self.agent_offset = 0.0
        else:
            self.agent_offset = loop_time - self.start_time
            
        self.agent_task = asyncio.create_task(
            self._record_track(track, self.agent_file, self.agent_offset, "agent")
        )

    async def _record_track(self, track: rtc.AudioTrack, file_path: str, offset: float, track_type: str):
        logger.info(f"Starting local audio recording for {track_type} track: {track.sid} with offset {offset:.2f}s")
        audio_stream = rtc.AudioStream(track)
        
        frames = []
        num_channels = None
        sample_rate = None

        try:
            async for frame_event in audio_stream:
                if self.stop_recording.is_set():
                    break

                frame = frame_event.frame
                if num_channels is None:
                    num_channels = frame.num_channels
                    sample_rate = frame.sample_rate

                frames.append(frame.data)
        except Exception as ex:
            logger.error(f"Error during {track_type} audio capturing: {ex}")
        finally:
            # Write frames to file in a separate thread to prevent event loop blocking
            if frames and num_channels is not None and sample_rate is not None:
                try:
                    await asyncio.to_thread(
                        self._save_frames_to_file, file_path, frames, num_channels, sample_rate, offset
                    )
                except Exception as e:
                    logger.error(f"Failed to save {track_type} frames to file: {e}")

    def _save_frames_to_file(self, file_path: str, frames: list, num_channels: int, sample_rate: int, offset: float):
        logger.info(f"Saving {len(frames)} frames of captured audio to {file_path}")
        with wave.open(file_path, "wb") as wav_file:
            wav_file.setnchannels(num_channels)
            wav_file.setsampwidth(2)  # 16-bit PCM = 2 bytes
            wav_file.setframerate(sample_rate)
            
            # Write initial silence padding if offset is positive
            if offset > 0:
                silence_bytes = int(offset * sample_rate) * num_channels * 2
                wav_file.writeframes(b'\x00' * silence_bytes)

            for frame_data in frames:
                wav_file.writeframes(frame_data)

    async def stop(self):
        self.stop_recording.set()
        
        # Wait for both tasks to finish
        tasks = []
        if self.candidate_task:
            tasks.append(self.candidate_task)
        if self.agent_task:
            tasks.append(self.agent_task)
            
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error while waiting for recording tasks completion: {e}")
        
        # Mix the recorded candidate and agent files
        try:
            await asyncio.to_thread(self._mix_files)
        except Exception as e:
            logger.error(f"Error mixing candidate and agent WAV files: {e}")

    def _mix_files(self):
        import struct
        
        has_candidate = os.path.exists(self.candidate_file)
        has_agent = os.path.exists(self.agent_file)
        
        if not has_candidate and not has_agent:
            logger.warning("No audio recorded for both agent and candidate.")
            return
            
        if has_candidate and not has_agent:
            logger.info("Only candidate audio recorded. Copying to main recording file.")
            if os.path.exists(self.recording_file):
                os.remove(self.recording_file)
            os.rename(self.candidate_file, self.recording_file)
            return
            
        if has_agent and not has_candidate:
            logger.info("Only agent audio recorded. Copying to main recording file.")
            if os.path.exists(self.recording_file):
                os.remove(self.recording_file)
            os.rename(self.agent_file, self.recording_file)
            return
            
        logger.info(f"Mixing candidate and agent audio files into {self.recording_file}")
        with wave.open(self.candidate_file, "rb") as w_cand, wave.open(self.agent_file, "rb") as w_agent:
            params_cand = w_cand.getparams()
            params_agent = w_agent.getparams()
            
            # Use candidate params as the base format (should be identical or very close)
            with wave.open(self.recording_file, "wb") as out:
                out.setparams(params_cand)
                
                if params_cand.framerate != params_agent.framerate:
                    logger.warning(
                        f"Sample rate mismatch during mixing: candidate={params_cand.framerate}Hz, agent={params_agent.framerate}Hz. "
                        "Mixing directly anyway."
                    )
                
                chunk_size = 4096
                while True:
                    data_cand = w_cand.readframes(chunk_size)
                    data_agent = w_agent.readframes(chunk_size)
                    
                    if not data_cand and not data_agent:
                        break
                        
                    if not data_cand:
                        out.writeframes(data_agent)
                        continue
                    if not data_agent:
                        out.writeframes(data_cand)
                        continue
                        
                    # Both have data, mix them (assumes 16-bit, 2 bytes/sample)
                    len_cand = len(data_cand)
                    len_agent = len(data_agent)
                    min_len = min(len_cand, len_agent)
                    
                    count = min_len // 2
                    fmt = f"{count}h"
                    samples_cand = struct.unpack(fmt, data_cand[:count*2])
                    samples_agent = struct.unpack(fmt, data_agent[:count*2])
                    
                    mixed = [max(-32768, min(32767, c + a)) for c, a in zip(samples_cand, samples_agent)]
                    mixed_bytes = struct.pack(fmt, *mixed)
                    
                    out.writeframes(mixed_bytes)
                    
                    # Handle residual bytes if chunk lengths differ slightly
                    if len_cand > min_len:
                        out.writeframes(data_cand[min_len:])
                    elif len_agent > min_len:
                        out.writeframes(data_agent[min_len:])
                        
        # Clean up temporary individual files
        try:
            if os.path.exists(self.candidate_file):
                os.remove(self.candidate_file)
            if os.path.exists(self.agent_file):
                os.remove(self.agent_file)
        except Exception as e:
            logger.error(f"Error deleting temp recording files: {e}")
