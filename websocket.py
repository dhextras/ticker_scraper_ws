import asyncio
import datetime
import hashlib
import json
import os
import socket
import threading
import time

import pytz
import websockets
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from dotenv import load_dotenv

from utils.logger import log_message
from utils.telegram_sender import send_telegram_message

load_dotenv()

# Constants
MESSAGES_FILE = "data/websocket_messages.json"
IGNORED_MESSAGES_FILE = "data/ignored_messages.json"
IGNORE_LIST_FILE = "data/ignore_list.json"
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", 8080))
TCP_HOST = os.getenv("TCP_HOST")
TCP_PORT = int(os.getenv("TCP_PORT", 3005))
TCP_SECRET = os.getenv("TCP_SECRET")
TCP_USERNAME = os.getenv("TCP_USERNAME")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SAVE_DELAY = 5.0  # Seconds to wait before saving messages

# In-memory message queues
pending_messages = []
pending_ignored_messages = []
last_message_time = datetime.datetime.now()
save_task = None


class EncryptedTcpClient:
    def __init__(self, server_ip, server_port, shared_secret, username):
        self.server_ip = server_ip
        self.server_port = server_port
        self.shared_secret = shared_secret
        self.username = username
        self.sock = None
        self.key = None
        self.connected = False
        self.thread = None
        self.message_queue = []
        self.lock = threading.Lock()

    def _get_utc_date(self):
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def _derive_key(self):
        combined = self.shared_secret + self._get_utc_date()
        return hashlib.sha256(combined.encode("utf-8")).digest()

    def _encrypt(self, plaintext: str) -> bytes:
        iv = b"\x00" * 16
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        padded = pad(plaintext.encode("utf-8"), AES.block_size)
        return cipher.encrypt(padded)

    def connect(self):
        """
        Connects to the server, performs authentication (IV + ciphertext),
        starts receiver and heartbeat threads.
        """
        while not self.connected:  # Keep trying to connect if disconnected
            try:
                # Establish TCP connection
                self.sock = socket.create_connection((self.server_ip, self.server_port))
                self.connected = True
                log_message(
                    f"[TCP] Connected to {self.server_ip}:{self.server_port}", "INFO"
                )

                # Derive fresh key daily
                self.key = self._derive_key()

                # 1) Send authentication payload (IV + encrypted username)
                iv = b"\x00" * 16
                encrypted_username = self._encrypt(self.username)
                self.sock.sendall(iv + encrypted_username)
                log_message(
                    f"[TCP] Sent encrypted auth for username '{self.username}'", "INFO"
                )

                # 2) Start background threads
                threading.Thread(target=self._receive_loop, daemon=True).start()
                threading.Thread(target=self._heartbeat_loop, daemon=True).start()
                threading.Thread(target=self._message_processor, daemon=True).start()

                # 3) Send initial hello after a short pause
                time.sleep(1)
                self.send_message("Hello, server!")

            except Exception as e:
                log_message(f"[TCP] Connection error: {e}", "ERROR")
                self.connected = False
                log_message("[TCP] Attempting to reconnect...", "WARNING")

                # Sleep before reconnecting
                time.sleep(5)

    def send_message(self, message):
        """
        Public method: queues a message to be encrypted and sent to the server.
        Can accept string or dict (which will be converted to JSON).
        """
        with self.lock:
            self.message_queue.append(message)

    def _message_processor(self):
        """Process messages from queue and send them to the server."""
        while True:
            if self.message_queue and self.connected:
                with self.lock:
                    message = self.message_queue.pop(0)

                try:
                    # Convert dict to JSON if needed
                    if isinstance(message, dict):
                        message = json.dumps(message)

                    # Send message
                    self.sock.sendall((f"{message}<END>").encode("utf-8"))
                    if "heartbeat" not in message.lower():
                        log_message(f"[TCP] Sent message: {message}", "INFO")
                except Exception as e:
                    log_message(f"[TCP] Send error: {e}", "ERROR")
                    self.connected = False
                    self.reconnect()

            time.sleep(0.1)  # Small delay to prevent CPU hogging

    def _receive_loop(self):
        while self.connected:
            try:
                data = self.sock.recv(4096)
                if not data:
                    log_message("[TCP] Server disconnected", "WARNING")
                    self.connected = False
                    self.reconnect()
                    break

                text = data.decode("utf-8", errors="ignore")
                log_message(f"[TCP] Received: {text}", "INFO")
            except Exception as e:
                log_message(f"[TCP] Receive error: {e}", "ERROR")
                self.connected = False
                self.reconnect()

    def _heartbeat_loop(self):
        while self.connected:
            time.sleep(60)  # Send heartbeat every 60 seconds
            try:
                self.send_message(f"HEARTBEAT")
            except Exception as e:
                log_message(f"[TCP] Heartbeat error: {e}", "ERROR")
                self.connected = False
                self.reconnect()

    def reconnect(self):
        """Attempt to reconnect to the server"""
        log_message("[TCP] Reconnecting...", "WARNING")
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

        # Wait a moment before reconnecting
        time.sleep(5)
        self.connect()

    def start(self):
        """Start the TCP client in a separate thread."""
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.connect, daemon=True)
            self.thread.start()
            log_message("[TCP] Client thread started", "INFO")
        else:
            log_message("[TCP] Client thread already running", "INFO")


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

    # Send notification about saved messages
    if filename == MESSAGES_FILE and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        asyncio.create_task(
            send_telegram_message(
                f"Saved {len(messages)} new messages to {filename}",
                TELEGRAM_BOT_TOKEN,
                TELEGRAM_CHAT_ID,
            )
        )


connected_clients = set()
tcp_client = None


async def handle_websocket(websocket, path):
    """Handle WebSocket connections and messages."""
    global last_message_time, pending_messages, pending_ignored_messages, tcp_client

    connected_clients.add(websocket)
    ignore_list = load_ignore_list()

    try:
        async for message in websocket:
            last_message_time = datetime.datetime.now()
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
                shares = data.get("shares", None)
                timestamp = datetime.datetime.now(pytz.timezone("US/Eastern")).strftime(
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

                if shares:
                    message_data["shares"] = str(shares)
                    message_data.pop("timestamp")
                    message_data.pop("old_message")

                if target:
                    message_data["target"] = target

                if should_ignore_message(sender, ticker, ignore_list):
                    pending_ignored_messages.append(message_data)
                    log_message(f"Ignored message: {message_data}", "INFO")
                else:
                    # Forward the message to the TCP server first
                    if tcp_client and tcp_client.connected:
                        if not data.get("processed", False):
                            tcp_client.send_message(message_data)
                    else:
                        log_message("TCP_CLIENT isn't Connected check why", "CRITICAL")

                    broadcast_message = json.dumps(message_data)
                    await asyncio.gather(
                        *[
                            client.send(broadcast_message)
                            for client in connected_clients
                        ]
                    )

                    pending_messages.append(message_data)

                    message = (
                        f"<b>New Message Received</b>\n\n"
                        f"<b>Ticker:</b> {message_data['ticker'].upper()}\n"
                        f"<b>Sender:</b> {message_data['sender']}\n"
                        f"<b>Name:</b> {message_data['name']}\n"
                        f"<b>Type:</b> {message_data['type']}\n"
                        f"<b>Timestamp:</b> {message_data['timestamp']}\n"
                    )

                    asyncio.create_task(
                        send_telegram_message(
                            message,
                            TELEGRAM_BOT_TOKEN,
                            TELEGRAM_CHAT_ID,
                        )
                    )

                log_message(f"[WS] [{timestamp}] - RECEIVED - {data}", "INFO")

    except websockets.ConnectionClosed:
        log_message("[WS] WebSocket connection closed", "INFO")
    except Exception as e:
        log_message(f"[WS] WebSocket error: {e}", "ERROR")
    finally:
        connected_clients.remove(websocket)


async def save_messages_after_delay():
    """Save pending messages after a delay if no new messages arrive."""
    global pending_messages, pending_ignored_messages

    while True:
        await asyncio.sleep(SAVE_DELAY)
        time_since_last_message = (
            datetime.datetime.now() - last_message_time
        ).total_seconds()

        # If enough time has passed, save the pending messages
        if time_since_last_message >= SAVE_DELAY:
            if pending_messages:
                messages_to_save = pending_messages.copy()
                pending_messages = []
                save_messages_to_file(messages_to_save, MESSAGES_FILE)
                log_message(f"Saved {len(messages_to_save)} messages to file", "INFO")

            if pending_ignored_messages:
                ignored_to_save = pending_ignored_messages.copy()
                pending_ignored_messages = []
                save_messages_to_file(ignored_to_save, IGNORED_MESSAGES_FILE)
                log_message(
                    f"Saved {len(ignored_to_save)} ignored messages to file", "INFO"
                )


async def main():
    """Start the WebSocket server, TCP client, and background save task."""
    global tcp_client

    # Initialize and start TCP client in a separate thread
    tcp_client = EncryptedTcpClient(
        server_ip=TCP_HOST,
        server_port=TCP_PORT,
        shared_secret=TCP_SECRET,
        username=TCP_USERNAME,
    )
    tcp_client.start()  # Start in a separate thread
    save_task = asyncio.create_task(save_messages_after_delay())

    server = await websockets.serve(
        handle_websocket, WS_HOST, WS_PORT, ping_interval=None, ping_timeout=None
    )

    log_message(f"WebSocket server running on ws://{WS_HOST}:{WS_PORT}", "INFO")
    log_message(f"TCP client connecting to {TCP_HOST}:{TCP_PORT}", "INFO")
    log_message(
        f"Messages will be saved after {SAVE_DELAY} seconds of inactivity", "INFO"
    )

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
            log_message(
                f"Saved remaining {len(pending_messages)} messages to file", "INFO"
            )
        if pending_ignored_messages:
            save_messages_to_file(pending_ignored_messages, IGNORED_MESSAGES_FILE)
            log_message(
                f"Saved remaining {len(pending_ignored_messages)} ignored messages to file",
                "INFO",
            )


if __name__ == "__main__":
    asyncio.run(main())
