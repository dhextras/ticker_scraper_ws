import asyncio
import fcntl
import json
import os
import traceback
from datetime import datetime

import pytz
import websockets
from dotenv import load_dotenv

load_dotenv()

# Constants
MESSAGES_FILE = "data/websocket_messages.json"
IGNORED_MESSAGES_FILE = "data/ignored_messages.json"
IGNORE_LIST_FILE = "data/ignore_list.json"
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", 8080))


def load_messages(filename):
    """Load messages from JSON file."""
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def load_ignore_list():
    """Load ignore list from JSON file."""
    try:
        with open(IGNORE_LIST_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def should_ignore_message(sender, ticker, ignore_list):
    """Check if message should be ignored based on sender and ticker."""
    if sender in ignore_list:
        return ticker.lower() in [t.lower() for t in ignore_list[sender]]
    return False


def save_message(message_data, filename):
    """Save message to specified JSON file with file locking and error handling."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    try:
        file_exists = os.path.exists(filename)
        with open(filename, "r+" if file_exists else "a+") as f:
            # Lock the file to prevent race conditions
            fcntl.flock(f, fcntl.LOCK_EX)

            try:
                if file_exists:
                    f.seek(0)
                    content = f.read().strip()
                    messages = json.loads(content) if content else []
                else:
                    messages = []

                messages.append(message_data)

                f.seek(0)
                f.truncate()
                json.dump(messages, f, indent=4)

            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        return True
    except Exception as e:
        print(f"Error saving message to {filename}: {str(e)}")
        print(traceback.format_exc())
        return False


connected_clients = set()


async def handle_websocket(websocket, path):
    """Handle WebSocket connections and messages."""
    connected_clients.add(websocket)
    ignore_list = load_ignore_list()

    try:
        async for message in websocket:
            data = json.loads(message)

            if data.get("request_old_messages", False):
                old_messages = load_messages(MESSAGES_FILE)
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

                message_data = {
                    "sender": sender,
                    "name": name,
                    "type": message_type,
                    "timestamp": timestamp,
                    "ticker": ticker,
                    "old_message": False,
                }
                if target:
                    message_data["target"] = target

                if should_ignore_message(sender, ticker, ignore_list):
                    save_message(message_data, IGNORED_MESSAGES_FILE)
                else:
                    broadcast_message = json.dumps(message_data)
                    await asyncio.gather(
                        *[
                            client.send(broadcast_message)
                            for client in connected_clients
                        ]
                    )
                    save_message(message_data, MESSAGES_FILE)

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
