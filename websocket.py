import asyncio
import json
import os
from datetime import datetime

import pytz
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


def save_message(sender, name, message_type, timestamp, ticker, target=None):
    """Save message to JSON file."""
    messages = load_messages()
    message = {
        "sender": sender,
        "name": name,
        "type": message_type,
        "timestamp": timestamp,
        "ticker": ticker,
    }
    if target:
        message["target"] = target

    messages.append(message)
    with open(MESSAGES_FILE, "w") as f:
        json.dump(messages, f, indent=4)


connected_clients = set()


async def handle_websocket(websocket, path):
    """Handle WebSocket connections and messages."""
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            # Check if the client wants old messages
            if data.get("request_old_messages", False):
                old_messages = load_messages()
                for msg in old_messages:
                    msg["old_message"] = True
                await websocket.send(json.dumps(old_messages))
            else:
                sender = data.get("sender", "Unknown - Sender")
                name = data.get("name", "Unknown - Sender Name")
                message_type = data.get("type", "default")
                ticker = data.get("ticker", "")
                target = data.get("target", None)
                timestamp = datetime.now(pytz.timezone("US/Eastern")).strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )

                broadcast_data = {
                    "sender": sender,
                    "name": name,
                    "type": message_type,
                    "timestamp": timestamp,
                    "ticker": ticker,
                    "old_message": False,
                }

                if target:
                    broadcast_data["target"] = target

                broadcast_message = json.dumps(broadcast_data)
                await asyncio.gather(
                    *[client.send(broadcast_message) for client in connected_clients]
                )
                save_message(sender, name, message_type, timestamp, ticker, target)

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
