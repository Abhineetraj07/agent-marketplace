"""
Launch the Agent Marketplace and all agent servers.

Usage:
    python run_marketplace.py          # Start everything
    python run_marketplace.py --demo   # Start everything + run demo queries
"""

import subprocess
import sys
import time
import os
import asyncio
import signal

CHATBOT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKETPLACE_PORT = os.environ.get("MARKETPLACE_PORT", "8000")

SERVICES = [
    {"name": "Marketplace", "cmd": [sys.executable, "-m", "marketplace.server"]},
    {"name": "FilmBot", "cmd": [sys.executable, "-m", "agents.filmbot_server"]},
    {"name": "FilmBot V2", "cmd": [sys.executable, "-m", "agents.filmbot_v2_server"]},
    {"name": "Melody Bot", "cmd": [sys.executable, "-m", "agents.melody_server"]},
    {"name": "Rock Agent", "cmd": [sys.executable, "-m", "agents.rock_server"]},
]

# Optional MCP server (add with --mcp flag)
MCP_SERVICE = {"name": "MCP Server", "cmd": [sys.executable, "-m", "mcp_server.server", "--sse", "8100"]}

processes: list[subprocess.Popen] = []


def start_all():
    print("=" * 60)
    print("  Agent Marketplace Launcher")
    print("=" * 60)

    for svc in SERVICES:
        print(f"\nStarting {svc['name']}...")
        proc = subprocess.Popen(
            svc["cmd"],
            cwd=CHATBOT_DIR,
            stdout=sys.stdout,
            stderr=sys.stderr,
            start_new_session=True,
        )
        processes.append(proc)
        # Give marketplace a head start so agents can register
        if svc["name"] == "Marketplace":
            time.sleep(2)
        else:
            time.sleep(1)

    print("\n" + "=" * 60)
    print("  All services started!")
    print("=" * 60)
    print("\nEndpoints:")
    print(f"  Marketplace:  http://0.0.0.0:{MARKETPLACE_PORT}")
    print("  FilmBot:      http://localhost:9001 (internal)")
    print("  FilmBot V2:   http://localhost:9002 (internal)")
    print("  Melody Bot:   http://localhost:9003 (internal)")
    print("  Rock Agent:   http://localhost:9004 (internal)")
    print(f"\nStorefront:     http://0.0.0.0:{MARKETPLACE_PORT}")
    print(f"Health:         curl http://0.0.0.0:{MARKETPLACE_PORT}/health")
    print("\nPress Ctrl+C to stop all services.\n")


async def run_demo():
    from marketplace.client import MarketplaceClient
    from marketplace.auth import MARKETPLACE_SECRET

    print("\n" + "=" * 60)
    print("  Running Demo")
    print("=" * 60)

    mc = MarketplaceClient(
        marketplace_url=f"http://localhost:{MARKETPLACE_PORT}",
        requester_id="demo",
        secret=MARKETPLACE_SECRET,
    )

    # Discover agents
    print("\n1. Discovering agents...")
    agents = await mc.discover_agents()
    print(f"   Found {len(agents)} agents:")
    for a in agents:
        print(f"   - {a['name']} ({a['agent_id']}) @ {a['url']}")

    # Call FilmBot
    print("\n2. Asking FilmBot: 'How many movies are in the dataset?'")
    response = await mc.call_agent("filmbot", "How many movies are in the dataset?")
    print(f"   Response: {response[:200]}")

    # Call Melody Bot
    print("\n3. Asking Melody: 'How many artists are in the database?'")
    response = await mc.call_agent("melody", "How many artists are in the database?")
    print(f"   Response: {response[:200]}")

    # Test token scoping
    print("\n4. Testing token scoping (get token for filmbot, try on melody)...")
    token = await mc.get_token("filmbot")
    import httpx
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        resp = await client.post(
            "http://localhost:9003/",
            headers={"Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": "1", "method": "message/send",
                  "params": {"message": {"role": "user", "parts": [{"text": "test"}], "messageId": "x"}}},
        )
        print(f"   Status: {resp.status_code} (expected 403)")
        print(f"   Response: {resp.json()}")

    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60)


def shutdown(signum=None, frame=None):
    print("\nShutting down all services...")
    for proc in processes:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
    for proc in processes:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    print("All services stopped.")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    start_all()

    if "--mcp" in sys.argv:
        print(f"\nStarting MCP Server (SSE on port 8100)...")
        proc = subprocess.Popen(
            MCP_SERVICE["cmd"],
            cwd=CHATBOT_DIR,
            stdout=sys.stdout,
            stderr=sys.stderr,
            start_new_session=True,
        )
        processes.append(proc)
        time.sleep(1)
        print("  MCP Server:   http://localhost:8100 (SSE)")

    if "--demo" in sys.argv:
        time.sleep(3)
        asyncio.run(run_demo())

    # Keep running until Ctrl+C
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()
