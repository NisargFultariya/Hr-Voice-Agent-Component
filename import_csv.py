import os
import csv
import requests
import sys

API_URL = os.getenv("HR_API_URL", "http://localhost:8080")

def main():
    csv_path = "candidates.csv"
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]

    # Create a sample candidate CSV if it doesn't exist
    if not os.path.exists(csv_path):
        print(f"Creating sample CSV file: {csv_path}")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("name,phone_number,role_applied,experience\n")
            f.write('"Your Name","+18315762291","Senior Software Engineer","5 years"\n')

    # Load agent details from agent.json
    import json
    agent_payload = {
        "name": "Priya",
        "persona_description": "You are Priya, a friendly talent recruiter representing Google.",
        "task_description": "Ask for notice period, location, and CTC expectation.",
        "voice_language": "en-IN",
        "voice_speaker": "priya",
        "initial_greeting": "Hello, thank you for taking my call. Am I speaking with Nisarg?",
        "knowledge_context": "FAQ:\nQ: What is the work model?\nA: We offer a hybrid model with 3 days in office."
    }

    agent_json_path = "agent.json"
    if not os.path.exists(agent_json_path):
        print(f"Creating template agent JSON: {agent_json_path}")
        with open(agent_json_path, "w", encoding="utf-8") as f:
            json.dump({
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
            }, f, indent=2)
    else:
        print(f"Reading agent details from {agent_json_path}...")
        try:
            with open(agent_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                agent_payload = {
                    "name": data.get("voice_bot_name", "Priya").strip(),
                    "persona_description": data.get("agent_role_persona", "").strip(),
                    "task_description": data.get("system_prompt_instructions", "").strip(),
                    "voice_language": "en-IN",
                    "voice_speaker": data.get("voice_profile", "priya").strip(),
                    "initial_greeting": data.get("initial_greeting_message", "").strip(),
                    "knowledge_context": data.get("knowledge_context_faqs", "").strip()
                }
        except Exception as err:
            print(f"Error loading agent.json: {err}. Using defaults.")

    print(f"Target Agent: {agent_payload['name']}")

    # 1. Check for existing agents and create if not exists
    print("Checking for existing recruiting agents...")
    try:
        res = requests.get(f"{API_URL}/api/agents")
        agents = res.json()
    except Exception as e:
        print(f"Error connecting to backend API: {e}")
        print("Please make sure the FastAPI orchestrator is running on port 8080.")
        return

    agent_id = None
    for ag in agents:
        if ag.get("name", "").lower() == agent_payload["name"].lower():
            agent_id = ag["id"]
            print(f"Using existing agent ID: {agent_id} (Name: {ag['name']})")
            break

    if agent_id is None:
        print(f"Creating new recruiting agent: {agent_payload['name']}...")
        res = requests.post(f"{API_URL}/api/agents", json=agent_payload)
        if res.status_code != 201:
            print(f"Agent creation failed: {res.text}")
            return
        agent_id = res.json()["id"]
        print(f"Created new Agent with ID: {agent_id}")

    # 2. Create Campaign
    campaign_name = f"Outbound Screening with {agent_payload['name']}"
    print(f"Creating recruiting campaign: '{campaign_name}'...")
    campaign_payload = {
        "agent_id": agent_id,
        "name": campaign_name,
        "scheduled_at": "2026-07-03T10:00:00"
    }
    res = requests.post(f"{API_URL}/api/campaigns", json=campaign_payload)
    if res.status_code != 201:
        print(f"Campaign creation failed: {res.text}")
        return
    campaign = res.json()
    campaign_id = campaign["id"]
    print(f"Campaign created with ID: {campaign_id}")

    # 3. Upload CSV candidates
    print(f"Uploading candidates CSV from: {csv_path}...")
    with open(csv_path, "rb") as f:
        files = {"file": f}
        res = requests.post(f"{API_URL}/api/campaigns/{campaign_id}/upload", files=files)
        if res.status_code != 200:
            print(f"CSV upload failed: {res.text}")
            return
        print(f"Successfully uploaded: {res.json()['message']}")

    # 4. Start Campaign
    print("Starting the campaign to trigger dial-outs...")
    res = requests.post(f"{API_URL}/api/campaigns/{campaign_id}/start")
    if res.status_code != 200:
        print(f"Failed to start campaign: {res.text}")
        return
    print(f"Success! Campaign status: {res.json()['status']}")
    print("The background scheduler will now process the calls under the configured pacing limits.")

    # 5. Wait for room creation and generate browser test URL
    import time
    print("\nWaiting for LiveKit dispatch room to be initialized by the scheduler (polling)...")
    
    playground_url = None
    for attempt in range(12):
        time.sleep(1.5)
        try:
            res = requests.get(f"{API_URL}/api/campaigns/{campaign_id}")
            candidates = res.json().get("candidates", [])
            if candidates:
                candidate_id = candidates[0]["id"]
                res = requests.get(f"{API_URL}/api/candidates/{candidate_id}/playground-url")
                if res.status_code == 200:
                    playground_url = res.json()["playground_url"]
                    break
        except Exception:
            pass

    if playground_url:
        print("\n" + "="*80)
        print("MOCK CALL BROWSER TEST LINK (No Twilio required!):")
        print("Open the link below in your browser, allow microphone, and talk with the agent:")
        print(playground_url)
        print("="*80 + "\n")
    else:
        print("\nCould not generate browser test URL. Please make sure the background docker containers are running and healthy.")

if __name__ == "__main__":
    main()
