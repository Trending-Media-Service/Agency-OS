import pytest
from unittest.mock import patch, MagicMock
from app.services.mcp import McpClient

@pytest.mark.asyncio
async def test_mcp_mock_mode_when_no_url():
    client = McpClient(server_url=None)
    tools = await client.list_tools()
    assert len(tools) > 0
    assert any(t["name"] == "shopify_get_shop_info" for t in tools)
    
    # Executing tool in mock mode
    result = await client.call_tool("shopify_get_shop_info", {})
    assert "Mock Ableys Shop" in result["content"][0]["text"]
    await client.close()

@pytest.mark.asyncio
async def test_mcp_real_mode_success():
    client = McpClient(server_url="http://localhost:8000/mcp")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jsonrpc": "2.0",
            "result": {
                "tools": [
                    {"name": "real_tool", "description": "A real tool", "inputSchema": {}}
                ]
            },
            "id": "list-1"
        }
        mock_post.return_value = mock_resp
        
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "real_tool"
        
    await client.close()

@pytest.mark.asyncio
async def test_mcp_real_mode_failure_list_tools():
    client = McpClient(server_url="http://localhost:8000/mcp")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = Exception("Connection refused")
        
        with pytest.raises(RuntimeError) as exc:
            await client.list_tools()
        assert "Real MCP server failure during list_tools" in str(exc.value)
        
    await client.close()

@pytest.mark.asyncio
async def test_mcp_real_mode_failure_call_tool():
    client = McpClient(server_url="http://localhost:8000/mcp")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = Exception("Timeout")
        
        with pytest.raises(RuntimeError) as exc:
            await client.call_tool("shopify_get_shop_info", {})
        assert "Real MCP server failure during call_tool" in str(exc.value)
        
    await client.close()
