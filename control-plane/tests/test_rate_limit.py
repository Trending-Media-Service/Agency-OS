import pytest

@pytest.mark.asyncio
async def test_rate_limiting_chat_endpoint(client):
    # We perform 6 rapid POST calls to /chat.
    # Since capacity is 5.0, the 6th call must be blocked with 429.
    responses = []
    for _ in range(6):
        res = await client.post("/chat", json={"text": "hello"})
        responses.append(res)

    # The first 5 calls should not be 429
    for i in range(5):
        assert responses[i].status_code != 429, f"Call {i+1} got blocked unexpectedly"

    # The 6th call must be 429
    last_res = responses[5]
    assert last_res.status_code == 429
    assert last_res.json() == {"detail": "Too many requests. Please try again later."}
    assert "Retry-After" in last_res.headers
    assert int(last_res.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_rate_limiting_tenants_endpoint(client):
    # We perform 6 rapid POST calls to /tenants.
    # The 6th call must be blocked with 429.
    responses = []
    for _ in range(6):
        res = await client.post("/tenants", json={"name": "test"})
        responses.append(res)

    # The first 5 calls should not be 429
    for i in range(5):
        assert responses[i].status_code != 429, f"Call {i+1} got blocked unexpectedly on /tenants"

    # The 6th call must be 429
    last_res = responses[5]
    assert last_res.status_code == 429
    assert last_res.json() == {"detail": "Too many requests. Please try again later."}
    assert "Retry-After" in last_res.headers
    assert int(last_res.headers["Retry-After"]) > 0
