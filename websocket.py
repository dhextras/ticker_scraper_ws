import asyncio
import json
import os
from datetime import datetime

import websockets
from dotenv import load_dotenv

load_dotenv()

# Constants
MESSAGES_FILE = "data/websocket_messages.json"
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", 8080))


def load_messages():
    """Load messages from JSON file."""
    try:
        with open(MESSAGES_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_message(sender, message_type, timestamp):
    """Save message to JSON file."""
    messages = load_messages()
    messages.append({"sender": sender, "type": message_type, "timestamp": timestamp})
    with open(MESSAGES_FILE, "w") as f:
        json.dump(messages, f, indent=4)


connected_clients = set()


async def handle_websocket(websocket, path):
    """Handle WebSocket connections and messages."""
    connected_clients.add(websocket)
    try:
        old_messages = load_messages()
        for msg in old_messages:
            await websocket.send(json.dumps(msg))

        async for message in websocket:
            data = json.loads(message)
            sender = data.get("sender", "Unknown")
            message_type = data.get("type", "default")
            timestamp = datetime.now().isoformat()

            save_message(sender, message_type, timestamp)

            broadcast_message = json.dumps(
                {"sender": sender, "type": message_type, "timestamp": timestamp}
            )

            await asyncio.gather(
                *[client.send(broadcast_message) for client in connected_clients]
            )
    except websockets.ConnectionClosed:
        pass
    finally:
        connected_clients.remove(websocket)


async def main():
    """Start the WebSocket server."""
    server = await websockets.serve(
        handle_websocket, WS_HOST, WS_PORT, ping_interval=None, ping_timeout=None
    )
    print(f"WebSocket server running on ws://{WS_HOST}:{WS_PORT}")
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())