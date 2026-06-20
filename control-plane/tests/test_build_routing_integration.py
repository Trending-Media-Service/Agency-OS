import pytest

async def test_actions_catalog_lists_build_deliver(client):
    r = await client.post("/tenants", json={"name": "BuildCatalog", "brand_name": "B"})
    tid = r.json()["tenant_id"]

    r = await client.get("/actions/catalog", headers={"X-Tenant-ID": tid})
    assert r.status_code == 200
    names = {a["name"] for a in r.json()["actions"]}
    assert "build_deliver" in names

async def test_actions_submit_build_deliver(client):
    r = await client.post("/tenants", json={"name": "BuildSubmit", "brand_name": "B"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]

    r = await client.post(
        "/actions",
        headers={"X-Tenant-ID": tid},
        json={
            "tool": "build_deliver",
            "brand_id": bid,
            "params": {
                "intent": "change hero color to blue",
                "repo": "git@github.com:test/brand-site.git"
            }
        },
    )
    assert r.status_code == 200, r.text
    cards = r.json()["cards"]
    assert len(cards) == 1
    assert cards[0]["action"] == "build.deliver"
    assert cards[0]["state"] == "AWAITING_APPROVAL" # Default Tier 1 requires approval

    # Verify it appears in the ops queue
    r = await client.get("/ops", headers={"X-Tenant-ID": tid})
    assert r.status_code == 200
    ops = r.json()
    assert any(o["action"] == "build.deliver" for o in ops)

async def test_chat_routes_build_intent(client):
    r = await client.post("/tenants", json={"name": "BuildChat", "brand_name": "B"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]

    # Send conversational code modification request
    r = await client.post(
        "/chat",
        headers={"X-Tenant-ID": tid},
        json={
            "brand_id": bid,
            "text": "change the hero background color to blue and increase font size"
        }
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "reply" in data
    assert len(data["cards"]) == 1
    card = data["cards"][0]
    assert card["action"] == "build.deliver"
    assert card["state"] == "AWAITING_APPROVAL"
    assert "Staging Preview" in card["preview"]

    # Verify it was written to the ops database table
    r = await client.get("/ops", headers={"X-Tenant-ID": tid})
    assert r.status_code == 200
    assert any(o["action"] == "build.deliver" for o in r.json())
