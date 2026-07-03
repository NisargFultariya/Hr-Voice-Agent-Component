import json
from hr_agent.metadata import parse_metadata

def test_parse_metadata_valid():
    data = {"call_id": 123, "candidate_name": "Test Candidate"}
    result = parse_metadata(json.dumps(data))
    assert result["call_id"] == 123
    assert result["candidate_name"] == "Test Candidate"

def test_parse_metadata_empty():
    assert parse_metadata("") == {}
    assert parse_metadata(None) == {}

def test_parse_metadata_invalid():
    assert parse_metadata("{invalid: json") == {}
