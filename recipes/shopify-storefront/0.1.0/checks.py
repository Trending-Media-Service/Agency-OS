import os
import sys
import asyncio

# Ensure we can import app from the control-plane path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../control-plane")))

def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for shopify-storefront recipe."""
    mcp_server_url = outputs.get("mcp_server_url", "")
    if not mcp_server_url:
        return {
            "mcp_server_reachable": False,
            "error": "No mcp_server_url output found"
        }

    from app.services.mcp import McpClient
    
    async def run_check():
        # Pass the server URL. If it's a test run or local dev, it falls back to mock.
        client = McpClient(server_url=mcp_server_url)
        try:
            info = await client.call_tool("shopify_get_shop_info", {})
            content = info.get("content", [{}])[0].get("text", "")
            return "shop_name" in content
        except Exception:
            return False
        finally:
            await client.close()

    import threading

    def run_in_thread():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(run_check())
        finally:
            new_loop.close()

    class CheckThread(threading.Thread):
        def __init__(self):
            super().__init__()
            self.result = False
        def run(self):
            self.result = run_in_thread()

    t = CheckThread()
    t.start()
    t.join()
    reachable = t.result

    return {
        "mcp_server_reachable": reachable,
        "storefront_active": reachable
    }
