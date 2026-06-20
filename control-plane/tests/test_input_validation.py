import pytest

@pytest.mark.asyncio
async def test_tenant_input_length_validation(client):
    # Operator auth is bypassed in the test client fixture, but we can send headers to be safe
    headers = {"Authorization": "Bearer default-dev-token"}

    # Case 1: Valid input (within limits) -> should pass schema validation
    # Note: Since the database is blank, this might return 404/500 later in execution, 
    # but schema validation passes, so it will NOT be 400!
    res_valid = await client.post(
        "/tenants",
        json={"name": "Short Name", "brand_name": "Short Brand"},
        headers=headers
    )
    assert res_valid.status_code != 400

    # Case 2: Name too long (201 chars) -> 400 Bad Request
    res_long_name = await client.post(
        "/tenants",
        json={"name": "a" * 201, "brand_name": "Short Brand"},
        headers=headers
    )
    assert res_long_name.status_code == 400
    assert "name" in res_long_name.text

    # Case 3: Brand name too long (201 chars) -> 400
    res_long_brand = await client.post(
        "/tenants",
        json={"name": "Short Name", "brand_name": "b" * 201},
        headers=headers
    )
    assert res_long_brand.status_code == 400
    assert "brand_name" in res_long_brand.text


@pytest.mark.asyncio
async def test_chat_input_length_validation(client):
    # X-Tenant-Id is required for /chat
    headers = {"X-Tenant-Id": "t-test-tenant"}

    # Case 1: Valid input (within limits) -> should not be 400
    res_valid = await client.post(
        "/chat",
        json={"brand_id": "b-brand", "text": "hello"},
        headers=headers
    )
    assert res_valid.status_code != 400

    # Case 2: Brand ID too long (101 chars) -> 400
    res_long_brand = await client.post(
        "/chat",
        json={"brand_id": "b" * 101, "text": "hello"},
        headers=headers
    )
    assert res_long_brand.status_code == 400
    assert "brand_id" in res_long_brand.text

    # Case 3: Text too long (5001 chars) -> 400
    res_long_text = await client.post(
        "/chat",
        json={"brand_id": "b-brand", "text": "t" * 5001},
        headers=headers
    )
    assert res_long_text.status_code == 400
    assert "text" in res_long_text.text


@pytest.mark.asyncio
async def test_intent_input_length_validation(client):
    headers = {"X-Tenant-Id": "t-test-tenant"}

    # Case 1: Valid input (within limits) -> should not be 400
    res_valid = await client.post(
        "/intents",
        json={"brand_id": "b-brand", "text": "hello", "domain": "provision"},
        headers=headers
    )
    assert res_valid.status_code != 400

    # Case 2: Domain too long (51 chars) -> 400
    res_long_domain = await client.post(
        "/intents",
        json={"brand_id": "b-brand", "text": "hello", "domain": "d" * 51},
        headers=headers
    )
    assert res_long_domain.status_code == 400
    assert "domain" in res_long_domain.text
