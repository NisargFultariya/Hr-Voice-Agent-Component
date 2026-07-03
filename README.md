# Standalone Candidate Call Automation System (hr-agent & hr-orchestrator)

A unified candidate calling system replacing external platforms. It includes `hr_orchestrator` (FastAPI + SQLite REST API) and `hr_agent` (Python LiveKit Agent Worker).

## Project Structure

```text
.
├── Dockerfile                  # Unified multi-service Docker container build
├── README.md                   # Running instructions
├── requirements.txt            # Python environment packages
├── agent.py                    # Voice worker main entrypoint
├── agent.json                  # Agent script & questions configuration
├── pytest.ini                  # Pytest runner configuration
├── hr_agent/                   # LiveKit Worker Package
│   ├── config.py               # Env configuration loading
│   ├── metadata.py             # Room/Job JSON metadata parser
│   ├── signal.py               # POST webhook client on call-completed
│   ├── openrouter.py           # LLM agent and fallback extract client
│   ├── job_state.py            # Caller state tracking
│   ├── compliance.py           # TRAI + DPDP notices
│   ├── dialogue/               # Custom dialogues
│   └── session/                # LiveKit session runners & recorders
├── hr_orchestrator/            # SQLite & REST API Platform
│   ├── main.py                 # FastAPI bootstrap & background scheduler task
│   ├── db.py                   # SQLAlchemy connection & DB schemas (SQLite)
│   ├── dispatch.py             # Active campaign polling & SIP dial triggering
│   ├── signals.py              # Webhook receipt from voice worker
│   ├── sip.py                  # LiveKit SDK SIP caller trigger
│   └── routes.py               # REST API endpoints (/api/agents, /api/campaigns, etc.)
├── deploy/
│   └── compose/
│       └── docker-compose.yml  # Local multi-service orchestration
└── tests/                      # Full Unit and Mock Test Suite
```

---

## Agent Configuration (`agent.json`)

The `agent.json` file in the root directory defines the recruiting bot's persona, greeting, and script. It supports configuring specific questions to ask:

```json
{
  "voice_bot_name": "Priya",
  "agent_role_persona": "You are Priya, a friendly talent recruiter representing Google.",
  "initial_greeting_message": "Hello, thank you for taking my call. Am I speaking with Nisarg?",
  "voice_profile": "priya",
  "system_prompt_instructions": "Ask for notice period, location, CTC expectation, and years of experience.",
  "questions_to_ask": [
    "What is your notice period?",
    "Where are you currently located?",
    "What is your CTC expectation?",
    "How many years of experience do you have?"
  ],
  "knowledge_context_faqs": "FAQ:\nQ: What is the work model?\nA: We offer a hybrid model with 3 days in office.\nQ: What is the location?\nA: The position is based in Bangalore."
}
```

---

## Call Recording and Mixing

During a call, the system captures **both** the candidate's voice (incoming) and the agent's voice (outgoing).
1. **Timestamp Alignment**: Audio offsets are calculated at the moment each stream publishes, padding the starting frames with silence (`b'\x00'`) to ensure both streams align perfectly in time.
2. **Mixing**: Upon call completion, the two separate PCM audio files are mixed using 16-bit PCM summation, clipped to prevent distortion, and saved to the final recording path: `./recordings/call-{call_id}.wav`.

---

## Getting Started

### Prerequisites
- Python 3.12+
- LiveKit project URL and API credentials
- Groq or OpenRouter API keys
- Sarvam AI API credentials

### 1. Installation
Initialize virtual environment and install requirements:
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Environment Configuration
Copy `.env.example` to `.env` and fill details:
```bash
cp .env.example .env
```
Ensure you have input valid credentials for `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, and `GROQ_API_KEY` (or `OPENROUTER_API_KEY`) & `SARVAM_API_KEY`.

### 3. Run Locally

#### Start the Orchestrator
```bash
python -m hr_orchestrator.main
```
FastAPI server will start on port `8080` (e.g. `http://localhost:8080`).

#### Start the Agent Voice Worker
Open a new shell, activate `venv`, and run:
```bash
python agent.py dev
```
It will automatically register with the LiveKit room services and wait for dispatched jobs.

---

## API Endpoints

- `POST /api/agents`: Create recruiting agent persona and script.
- `POST /api/campaigns`: Create calling campaign.
- `POST /api/campaigns/{id}/upload`: Upload candidate CSV containing headers `name` and `phone_number`.
- `POST /api/campaigns/{id}/candidate`: Single quick-add candidate.
- `POST /api/quick-call`: Auto-create defaults and schedule immediate candidate calling.
- `GET /api/dashboard/stats`: Retrieve outcomes statistics.

---

## Running Tests
Run the test suite using `pytest`:
```bash
python -m pytest tests/
```
