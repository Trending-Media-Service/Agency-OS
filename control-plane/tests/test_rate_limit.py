import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_rate_limiting_chat_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # We perform 6 rapid POST calls to /chat.
        # Since capacity is 5.0, the 6th call must be blocked with 429.
        # Note: We send invalid payloads, but rate limiter intercepts before route handler/schema validation!
        
        responses = []
        for _ in range(6):
            res = await ac.post("/chat", json={"text": "hello"})
            responses.append(res)
        
        # The first 5 calls should not be 429 (they will probably be 401 because X-Tenant-Id is missing, which is fine)
        for i in range(5):
            assert responses[i].status_code != 429, f"Call {i+1} got blocked unexpectedly"
            
        # The 6th call must be 429
        last_res = responses[5]
        assert last_res.status_code == 429
        assert last_res.json() == {"detail": "Too many requests. Please try again later."}
        assert "Retry-After" in last_res.headers
        assert int(last_res.headers["Retry-After"]) > 0
