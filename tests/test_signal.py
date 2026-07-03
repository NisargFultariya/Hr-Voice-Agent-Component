from unittest.mock import patch, MagicMock
from hr_agent.signal import send_completion_signal

@patch("requests.post")
def test_send_completion_signal_success(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    payload = {"call_id": 1}
    result = send_completion_signal(payload)
    assert result is True

@patch("requests.post")
def test_send_completion_signal_failure(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_post.return_value = mock_response

    payload = {"call_id": 1}
    result = send_completion_signal(payload)
    assert result is False
