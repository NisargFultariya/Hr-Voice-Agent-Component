import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, TypeDecorator
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_PATH = os.getenv("ORCHESTRATOR_DB_PATH", "./data/hr_orchestrator.db")
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Ensure data directory exists
db_dir = os.path.dirname(DATABASE_PATH)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# SQLAlchemy helper type to handle JSON strings in SQLite
class JSONEncodedDict(TypeDecorator):
    impl = Text

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return json.loads(value)
        except Exception:
            return value

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    persona_description = Column(Text, nullable=False)
    task_description = Column(Text, nullable=False)
    voice_language = Column(String, default="en-IN")
    voice_speaker = Column(String, default="priya")
    system_prompt = Column(Text, nullable=False)
    initial_greeting = Column(Text, nullable=True)
    knowledge_context = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaigns = relationship("Campaign", back_populates="agent")

class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    status = Column(String, default="draft")  # draft, scheduled, running, completed, failed
    retry_limit = Column(Integer, default=1)
    retry_delay_minutes = Column(Integer, default=15)
    max_concurrent_calls = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="campaigns")
    candidates = relationship("Candidate", back_populates="campaign")

class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    extra_fields = Column(JSONEncodedDict, default=dict)
    call_status = Column(String, default="pending")  # pending, calling, completed, failed, retry_queued, busy, no_answer
    attempt_count = Column(Integer, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign = relationship("Campaign", back_populates="candidates")
    calls = relationship("Call", back_populates="candidate")

class Call(Base):
    __tablename__ = "calls"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    recording_url = Column(String, nullable=True)
    transcript = Column(JSONEncodedDict, default=list)
    extracted_data = Column(JSONEncodedDict, default=dict)
    disposition = Column(String, nullable=True)
    raw_status_from_twilio = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    candidate = relationship("Candidate", back_populates="calls")
    events = relationship("CallEvent", back_populates="call")

class CallEvent(Base):
    __tablename__ = "call_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    call_id = Column(Integer, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)  # initiated, ringing, answered, ended, failed
    payload = Column(JSONEncodedDict, default=dict)
    timestamp = Column(DateTime, default=datetime.utcnow)

    call = relationship("Call", back_populates="events")

def init_db():
    Base.metadata.create_all(bind=engine)
