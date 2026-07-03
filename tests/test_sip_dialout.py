import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from hr_agent.session.pstn import trigger_outbound_dial
from livekit import api

@pytest.mark.asyncio
@patch("os.getenv")
async def test_trigger_outbound_dial_success(mock_getenv):
    # Setup mock environment variable
    mock_getenv.side_effect = lambda k, d=None: {
        "LIVEKIT_SIP_TRUNK_ID": "ST_test_trunk"
    }.get(k, d)

    # Mock JobContext
    mock_ctx = MagicMock()
    mock_ctx.room.name = "test-room"
    
    mock_sip = AsyncMock()
    mock_ctx.api.sip = mock_sip
    
    mock_sip.create_sip_participant.return_value = MagicMock()

    await trigger_outbound_dial(mock_ctx, "+919999999999")

    # Verify that create_sip_participant was called with correct arguments
    mock_sip.create_sip_participant.assert_called_once()
    args = mock_sip.create_sip_participant.call_args[0]
    request = args[0]
    
    assert request.room_name == "test-room"
    assert request.sip_trunk_id == "ST_test_trunk"
    assert request.sip_call_to == "+919999999999"
    assert request.participant_identity == "candidate_+919999999999"
