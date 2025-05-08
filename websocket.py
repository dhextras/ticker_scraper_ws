import asyncio
import json
import os
import socket
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
TCP_HOST = os.getenv("TCP_HOST")
TCP_PORT = int(os.getenv("TCP_PORT", 3000))
TCP_SECRET = os.getenv("TCP_SECRET")
SAVE_DELAY = 5.0  # Seconds to wait before saving messages

# In-memory message queues
pending_messages = []
pending_ignored_messages = []
last_message_time = datetime.now()
save_task = None
tcp_client = None


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


class TCPClient:
    """TCP Client to forward messages to a TCP server."""

    def __init__(self, host, port, secret):
        self.host = host
        self.port = port
        self.secret = secret
        self.socket = None
        self.connected = False
        self.reconnect_task = None

    async def connect(self):
        """Connect to the TCP server."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setblocking(False)

            # Connect to the server asynchronously
            await asyncio.get_event_loop().sock_connect(
                self.socket, (self.host, self.port)
            )

            # Send authentication message
            auth_message = json.dumps({"command": "auth", "secret": self.secret})
            await asyncio.get_event_loop().sock_sendall(
                self.socket, (auth_message + "\n").encode()
            )

            print(f"Connected to TCP server at {self.host}:{self.port}")
            self.connected = True

            if self.reconnect_task:
                self.reconnect_task.cancel()
                self.reconnect_task = None

            return True
        except Exception as e:
            print(f"Failed to connect to TCP server: {e}")
            self.connected = False
            self.schedule_reconnect()
            return False

    def schedule_reconnect(self):
        """Schedule a reconnection attempt."""
        if not self.reconnect_task or self.reconnect_task.done():
            self.reconnect_task = asyncio.create_task(self.reconnect())

    async def reconnect(self):
        """Attempt to reconnect to the TCP server after a delay."""
        await asyncio.sleep(5)  # Wait 5 seconds before reconnecting
        print("Attempting to reconnect to TCP server...")
        await self.connect()

    async def send_message(self, message_data):
        """Send a message to the TCP server."""
        if not self.connected:
            await self.connect()
            if not self.connected:
                return False

        try:
            message_json = json.dumps(message_data)
            await asyncio.get_event_loop().sock_sendall(
                self.socket, (message_json + "<END>").encode()
            )
            return True
        except Exception as e:
            print(f"Error sending message to TCP server: {e}")
            self.connected = False
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            self.schedule_reconnect()
            return False


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
    global last_message_time, pending_messages, pending_ignored_messages, tcp_client

    connected_clients.add(websocket)
    ignore_list = load_ignore_list()

    try:
        async for message in websocket:
            last_message_time = datetime.now()
            data = json.loads(message)

            # ping (1) & pong (2)
            if data == "[1":
                await websocket.send("[2")
            elif data.get("request_old_messages", False):
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

                if not ticker or ticker == "":
                    continue

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
                    # Forward the message to the TCP server first
                    if tcp_client:
                        await tcp_client.send_message(message_data)
                    else:
                        print("Critical: TCP_CLIENT isn't Connected check why")

                    broadcast_message = json.dumps(message_data)
                    await asyncio.gather(
                        *[
                            client.send(broadcast_message)
                            for client in connected_clients
                        ]
                    )

                    pending_messages.append(message_data)

                print(f"[{timestamp}] - RECEIVED - {data}")

    except websockets.ConnectionClosed:
        pass
    finally:
        connected_clients.remove(websocket)


async def main():
    """Start the WebSocket server, TCP client, and background save task."""
    global tcp_client

    tcp_client = TCPClient(TCP_HOST, TCP_PORT, TCP_SECRET)
    asyncio.create_task(tcp_client.connect())

    save_task = asyncio.create_task(save_messages_after_delay())

    server = await websockets.serve(
        handle_websocket, WS_HOST, WS_PORT, ping_interval=None, ping_timeout=None
    )

    print(f"WebSocket server running on ws://{WS_HOST}:{WS_PORT}")
    print(f"TCP client connecting to {TCP_HOST}:{TCP_PORT}")
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
