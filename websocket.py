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
IGNORED_MESSAGES_FILE = "data/ignored_messages.json"
IGNORE_LIST_FILE = "data/ignore_list.json"
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", 8080))
SAVE_DELAY = 3.0  # Seconds to wait before saving messages

# In-memory message queues
pending_messages = []
pending_ignored_messages = []
last_message_time = datetime.now()
save_task = None


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


def save_messages_to_file(messages, filename):
    """Save collected messages to the specified JSON file."""
    if not messages:
        return

    os.makedirs(os.path.dirname(filename), exist_ok=True)

    existing_messages = load_messages(filename)

    existing_messages.extend(messages)

    with open(filename, "w") as f:
        json.dump(existing_messages, f, indent=4)


async def save_messages_after_delay():
    """Save pending messages after a delay if no new messages arrive."""
    global pending_messages, pending_ignored_messages

    while True:
        await asyncio.sleep(SAVE_DELAY)
        time_since_last_message = (datetime.now() - last_message_time).total_seconds()

        # If enough time has passed, save the pending messages
        if time_since_last_message >= SAVE_DELAY:
            if pending_messages:
                messages_to_save = pending_messages.copy()
                pending_messages = []
                save_messages_to_file(messages_to_save, MESSAGES_FILE)

            if pending_ignored_messages:
                ignored_to_save = pending_ignored_messages.copy()
                pending_ignored_messages = []
                save_messages_to_file(ignored_to_save, IGNORED_MESSAGES_FILE)


connected_clients = set()


async def handle_websocket(websocket, path):
    """Handle WebSocket connections and messages."""
    global last_message_time, pending_messages, pending_ignored_messages

    connected_clients.add(websocket)
    ignore_list = load_ignore_list()

    try:
        async for message in websocket:
            last_message_time = datetime.now()

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
                    pending_ignored_messages.append(message_data)
                else:
                    broadcast_message = json.dumps(message_data)
                    await asyncio.gather(
                        *[
                            client.send(broadcast_message)
                            for client in connected_clients
                        ]
                    )

                    pending_messages.append(message_data)

    except websockets.ConnectionClosed:
        pass
    finally:
        connected_clients.remove(websocket)


async def main():
    """Start the WebSocket server and background save task."""
    save_task = asyncio.create_task(save_messages_after_delay())
    server = await websockets.serve(
        handle_websocket, WS_HOST, WS_PORT, ping_interval=None, ping_timeout=None
    )

    print(f"WebSocket server running on ws://{WS_HOST}:{WS_PORT}")
    print(f"Messages will be saved after {SAVE_DELAY} seconds of inactivity")

    try:
        await server.wait_closed()
    finally:
        if save_task:
            save_task.cancel()
            try:
                await save_task
            except asyncio.CancelledError:
                pass

            if pending_messages:
                save_messages_to_file(pending_messages, MESSAGES_FILE)
            if pending_ignored_messages:
                save_messages_to_file(pending_ignored_messages, IGNORED_MESSAGES_FILE)


if __name__ == "__main__":
    asyncio.run(main())
