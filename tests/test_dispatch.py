import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from hr_orchestrator.dispatch import check_calling_hours, process_call
from hr_orchestrator.db import Campaign, Candidate, Agent

@patch("hr_orchestrator.dispatch.datetime")
@patch("os.getenv")
def test_check_calling_hours_in_window(mock_getenv, mock_datetime):
    mock_getenv.side_effect = lambda k, d=None: {
        "CALL_WINDOW_START": "09:00",
        "CALL_WINDOW_END": "20:00"
    }.get(k, d)
    
    mock_now = MagicMock()
    mock_now.strftime.return_value = "12:00"
    mock_datetime.now.return_value = mock_now

    assert check_calling_hours() is True

@patch("hr_orchestrator.dispatch.datetime")
@patch("os.getenv")
def test_check_calling_hours_out_window(mock_getenv, mock_datetime):
    mock_getenv.side_effect = lambda k, d=None: {
        "CALL_WINDOW_START": "09:00",
        "CALL_WINDOW_END": "20:00"
    }.get(k, d)

    mock_now = MagicMock()
    mock_now.strftime.return_value = "22:00"
    mock_datetime.now.return_value = mock_now

    assert check_calling_hours() is False

@pytest.mark.asyncio
@patch("hr_orchestrator.dispatch.SessionLocal")
@patch("os.getenv")
@patch("livekit.api.LiveKitAPI")
async def test_process_call_dispatches_agent(mock_lk_api, mock_getenv, mock_session_local):
    # Mock environment variables
    mock_getenv.side_effect = lambda k, d=None: {
        "LIVEKIT_URL": "ws://example.com",
        "LIVEKIT_API_KEY": "key",
        "LIVEKIT_API_SECRET": "secret",
        "LIVEKIT_AGENT_NAME": "hr-recruiter-agent"
    }.get(k, d)

    # Mock DB Session
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db
    
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_filter = MagicMock()
    mock_query.filter.return_value = mock_filter

    # Mock campaign and agent
    mock_agent = Agent(system_prompt="prompt", voice_language="en-IN", voice_speaker="priya")
    mock_campaign = Campaign(id=1, name="Campaign 1", agent=mock_agent, retry_limit=1, retry_delay_minutes=15, max_concurrent_calls=1)
    mock_candidate = Candidate(id=1, name="Candidate 1", phone_number="+919999999999", attempt_count=0)

    mock_filter.first.side_effect = [mock_candidate, mock_campaign]

    # Mock LiveKit client
    mock_client = AsyncMock()
    mock_lk_api.return_value.__aenter__.return_value = mock_client
    
    mock_dispatch = AsyncMock()
    mock_client.agent_dispatch = mock_dispatch
    
    mock_res = MagicMock()
    mock_res.id = "disp-123"
    mock_dispatch.create_dispatch.return_value = mock_res

    # Run process_call
    await process_call(mock_candidate.id, mock_campaign.id)

    # Verify that agent_dispatch.create_dispatch was called
    mock_dispatch.create_dispatch.assert_called_once()
    args = mock_dispatch.create_dispatch.call_args[0]
    request = args[0]
    
    assert request.agent_name == "hr-recruiter-agent"
    assert "Candidate 1" in request.metadata
    assert "+919999999999" in request.metadata
