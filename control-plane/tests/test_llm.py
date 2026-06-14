import pytest
import os
import httpx
from app.services.llm import VertexAIClient
from unittest.mock import patch, MagicMock

def test_vertex_ai_client_mock_mode():
    client = VertexAIClient()
    res = client.generate_edits("make app blue", "context files")
    assert res["explanation"] == "Simulated edits for testing"
    assert res["edits"][0]["path"] == "src/App.js"
    assert res["edits"][0]["content"] == "function App() {\n  return <Hero color=\"blue\" />;\n}\n"

@patch("app.services.llm.httpx.Client.post")
@patch("google.auth.default")
def test_vertex_ai_client_real_api_mocked(mock_auth, mock_post):
    # Temporarily disable AOS_ENV=test
    old_env = os.environ.get("AOS_ENV")
    os.environ["AOS_ENV"] = "production"

    try:
        # Mock Google auth credentials
        mock_creds = MagicMock()
        mock_creds.token = "mock-bearer-token"
        mock_creds.refresh = MagicMock()
        mock_auth.return_value = (mock_creds, "mock-project-id")

        # Mock successful response
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"explanation": "Updated colors", "edits": [{"path": "src/App.js", "action": "modify", "content": "hello"}]}'
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        client = VertexAIClient(project_id="test-project")
        res = client.generate_edits("make it simple", "context")
        assert res["explanation"] == "Updated colors"
        assert res["edits"][0]["path"] == "src/App.js"
        assert res["edits"][0]["content"] == "hello"

    finally:
        if old_env:
            os.environ["AOS_ENV"] = old_env
        else:
            del os.environ["AOS_ENV"]
