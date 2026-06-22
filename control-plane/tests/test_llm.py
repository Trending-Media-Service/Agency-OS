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


@pytest.mark.asyncio
@patch("app.services.llm.httpx.AsyncClient.post")
@patch("google.auth.default")
async def test_vertex_ai_client_personalized_content_mocked(mock_auth, mock_post, session):
    # Temporarily disable AOS_ENV=test
    old_env = os.environ.get("AOS_ENV")
    os.environ["AOS_ENV"] = "production"

    try:
        # Mock Google auth credentials
        mock_creds = MagicMock()
        mock_creds.token = "mock-bearer-token"
        mock_creds.refresh = MagicMock()
        mock_auth.return_value = (mock_creds, "mock-project-id")

        # Mock successful async response
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "This is a highly personalized ad headline written in a playful, sensory-friendly tone!"
                            }
                        ]
                    }
                }
            ]
        }
        
        # Async mock for httpx.AsyncClient.post
        async def mock_post_coro(*args, **kwargs):
            return mock_response
        mock_post.side_effect = mock_post_coro

        client = VertexAIClient(project_id="test-project")
        res = await client.generate_personalized_content(
            tenant_id="t1", 
            brand_id="b1", 
            prompt="write a headline",
            session=session
        )
        assert "sensory-friendly" in res
        assert "playful" in res

    finally:
        if old_env:
            os.environ["AOS_ENV"] = old_env
        else:
            del os.environ["AOS_ENV"]


@pytest.mark.asyncio
@patch("app.services.llm.httpx.AsyncClient.post")
@patch("google.auth.default")
async def test_vertex_ai_client_lora_routing_real_mode(mock_auth, mock_post, session):
    # Set to production mode to avoid mock short-circuiting
    old_env = os.environ.get("AOS_ENV")
    os.environ["AOS_ENV"] = "production"

    try:
        # Mock Google auth credentials
        mock_creds = MagicMock()
        mock_creds.token = "mock-bearer-token"
        mock_creds.refresh = MagicMock()
        mock_auth.return_value = (mock_creds, "mock-project-id")

        # Seed the custom Tenant LoRA Adapter in database
        from app.models import BrandProperty
        lora_endpoint = "https://us-central1-aiplatform.googleapis.com/v1/projects/test-project/locations/us-central1/endpoints/t1-lora-endpoint:predict"
        lora_prop = BrandProperty(
            tenant_id="t1",
            brand_id="b1",
            type="lora_adapter",
            provider="vertex-ai",
            status="active",
            findings={"endpoint_url": lora_endpoint}
        )
        session.add(lora_prop)
        await session.commit()

        # Mock successful async response from LoRA endpoint
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "Optimized copy generated directly by the custom fine-tuned LoRA adapter!"
                            }
                        ]
                    }
                }
            ]
        }
        
        async def mock_post_coro(*args, **kwargs):
            return mock_response
        mock_post.side_effect = mock_post_coro

        client = VertexAIClient(project_id="test-project")
        res = await client.generate_personalized_content(
            tenant_id="t1", 
            brand_id="b1", 
            prompt="write a headline",
            session=session
        )
        
        # Verify that the HTTP call was dynamically routed to the custom LoRA endpoint!
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        target_url = args[0]
        assert target_url == lora_endpoint
        assert "LoRA" in res

    finally:
        if old_env:
            os.environ["AOS_ENV"] = old_env
        else:
            del os.environ["AOS_ENV"]


