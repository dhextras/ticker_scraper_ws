import asyncio
import datetime
import hashlib
import json
import os
import shutil
import socket
import threading
import time

import pytz
import websockets
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from dotenv import load_dotenv

from utils.logger import log_message
from utils.telegram_sender import send_telegram_message

load_dotenv()

# Constants
MESSAGES_FILE = "data/websocket_messages.json"
IGNORED_MESSAGES_FILE = "data/ignored_messages.json"
IGNORE_LIST_FILE = "data/ignore_list.json"
BACKUP_BASE_DIR = "data/backup"
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
last_actual_message_time = datetime.datetime.now()
save_task = None
backup_task = None


class EncryptedTcpClient:
    def __init__(self, server_ip, server_port, shared_secret, username):
        self.server_ip = server_ip
        self.server_port = server_port
        self.shared_secret = shared_secret
        self.username = username
        self.sock = None
        self.key = None
        self.connected = False
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.stop_event = threading.Event()

    def _get_utc_date(self):
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def _derive_key(self):
        combined = self.shared_secret + self._get_utc_date()
        return hashlib.sha256(combined.encode("utf-8")).digest()

    def _encrypt(self, plaintext: str) -> bytes:
        iv = b"\x00" * 16
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))

    def _decrypt(self, ciphertext: bytes) -> str:
        iv = b"\x00" * 16
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        decrypted_padded = cipher.decrypt(ciphertext)
        return unpad(decrypted_padded, AES.block_size).decode("utf-8")

    def connect(self):
        threading.Thread(target=self._connection_loop, daemon=True).start()

    def _connection_loop(self):
        while not self.stop_event.is_set():
            with self.lock:
                while self.connected and not self.stop_event.is_set():
                    self.cond.wait()

            if self.stop_event.is_set():
                break

            log_message("Attempting to connect...", "INFO")
            try:
                self.sock = socket.create_connection(
                    (self.server_ip, self.server_port), timeout=60
                )
                self.sock.settimeout(140)
                self.key = self._derive_key()

                # Authenticate
                iv = b"\x00" * 16
                encrypted_username = self._encrypt(self.username)
                self.sock.sendall(iv + encrypted_username)
                log_message(
                    f"[TCP] Sent encrypted auth for username '{self.username}'", "INFO"
                )

                with self.lock:
                    self.connected = True

                log_message(
                    f"[TCP] Connected to {self.server_ip}:{self.server_port}", "INFO"
                )

                threading.Thread(target=self._receive_loop, daemon=True).start()
                threading.Thread(target=self._heartbeat_loop, daemon=True).start()

                time.sleep(0.5)
                self.send_message("Hello, server!")

            except Exception as e:
                log_message(f"[TCP] Connection error: {e}", "ERROR")
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                    self.sock = None
                time.sleep(2)

    def disconnect(self):
        self.stop_event.set()
        with self.lock:
            self.connected = False
            self.cond.notify()
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
        log_message("[TCP] Server disconnected", "WARNING")

    def send_message(self, message: str):
        with self.lock:
            if not self.connected:
                log_message("Cannot send message: not connected", "WARNING")
                return

        try:
            framed = (message + "<END>").encode("utf-8")
            self.sock.sendall(framed)
            if message != "HEARTBEAT":
                log_message(f"Sent: {message}", "INFO")
        except Exception as e:
            log_message(f"Send error: {e}", "ERROR")
            with self.lock:
                self.connected = False
                self.cond.notify()

    def _receive_loop(self):
        buffer = b""
        while not self.stop_event.is_set():
            try:
                data = self.sock.recv(4096)
                if not data:
                    log_message("Server closed connection", "WARNING")
                    break

                buffer += data
                while b"<END>" in buffer:
                    msg, buffer = buffer.split(b"<END>", 1)
                    try:
                        decrypted = self._decrypt(msg)
                        log_message(f"Received (decrypted): {decrypted}", "INFO")
                    except Exception:
                        text = msg.decode("utf-8", errors="ignore")
                        log_message(f"Received (plaintext): {text}", "INFO")

            except Exception as e:
                log_message(f"Receive error: {e}", "ERROR")
                break

        with self.lock:
            self.connected = False
            self.cond.notify()

    def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            time.sleep(5)
            self.send_message("HEARTBEAT")


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


def create_backup_path(date_obj):
    """Create backup path based on date: data/backup/YYYY/MM/filename_YYYY-MM-DD.json"""
    year = date_obj.strftime("%Y")
    month = date_obj.strftime("%m")
    day = date_obj.strftime("%Y-%m-%d")

    backup_dir = os.path.join(BACKUP_BASE_DIR, year, month)
    os.makedirs(backup_dir, exist_ok=True)

    return backup_dir, day


def backup_file(source_file, date_obj):
    """Create a backup of the source file with organized folder structure."""
    if not os.path.exists(source_file):
        log_message(
            f"[BACKUP] Source file {source_file} doesn't exist, skipping backup",
            "WARNING",
        )
        return

    try:
        backup_dir, day = create_backup_path(date_obj)

        base_filename = os.path.splitext(os.path.basename(source_file))[0]
        backup_filename = f"{base_filename}_{day}.json"
        backup_path = os.path.join(backup_dir, backup_filename)

        shutil.copy2(source_file, backup_path)
        log_message(f"[BACKUP] Created backup: {backup_path}", "INFO")

        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            asyncio.create_task(
                send_telegram_message(
                    f"Daily backup created: {backup_filename}",
                    TELEGRAM_BOT_TOKEN,
                    TELEGRAM_CHAT_ID,
                )
            )

    except Exception as e:
        log_message(f"[BACKUP] Failed to create backup for {source_file}: {e}", "ERROR")


async def daily_backup_task():
    """Task that runs daily to create backups of message files."""
    last_backup_date = None

    while True:
        try:
            current_date = datetime.datetime.now().date()

            if last_backup_date != current_date:
                log_message("[BACKUP] Starting daily backup process", "INFO")

                backup_file(MESSAGES_FILE, current_date)
                backup_file(IGNORED_MESSAGES_FILE, current_date)

                last_backup_date = current_date
                log_message("[BACKUP] Daily backup process completed", "INFO")

            await asyncio.sleep(3600)

        except Exception as e:
            log_message(f"[BACKUP] Error in daily backup task: {e}", "ERROR")
            await asyncio.sleep(3600)


connected_clients = set()
tcp_client = None


async def handle_websocket(websocket, path):
    """Handle WebSocket connections and messages."""
    global last_actual_message_time, pending_messages, pending_ignored_messages, tcp_client

    connected_clients.add(websocket)
    ignore_list = load_ignore_list()

    try:
        async for message in websocket:
            data = json.loads(message)

            # ping (1) & pong (2)
            if data == "[1":
                await websocket.send("[2")
                continue
            elif data.get("request_old_messages", False):
                last_actual_message_time = datetime.datetime.now()
                old_messages = load_messages(MESSAGES_FILE)
                for msg in old_messages:
                    msg["old_message"] = True
                await websocket.send(json.dumps(old_messages))
                continue

            last_actual_message_time = datetime.datetime.now()

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
                        tcp_client.send_message(str(message_data))
                else:
                    log_message("TCP_CLIENT isn't Connected check why", "CRITICAL")

                broadcast_message = json.dumps(message_data)
                await asyncio.gather(
                    *[client.send(broadcast_message) for client in connected_clients]
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
    """Save pending messages after a delay if no new actual messages arrive."""
    global pending_messages, pending_ignored_messages

    while True:
        await asyncio.sleep(SAVE_DELAY)
        time_since_last_message = (
            datetime.datetime.now() - last_actual_message_time
        ).total_seconds()

        # If enough time has passed since last actual message, save the pending messages
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
    """Start the WebSocket server, TCP client, backup task, and background save task."""
    global tcp_client, backup_task

    # Initialize and start TCP client in a separate thread
    tcp_client = EncryptedTcpClient(
        server_ip=TCP_HOST,
        server_port=TCP_PORT,
        shared_secret=TCP_SECRET,
        username=TCP_USERNAME,
    )
    tcp_client.connect()
    save_task = asyncio.create_task(save_messages_after_delay())
    backup_task = asyncio.create_task(daily_backup_task())

    server = await websockets.serve(
        handle_websocket, WS_HOST, WS_PORT, ping_interval=None, ping_timeout=None
    )

    log_message(f"WebSocket server running on ws://{WS_HOST}:{WS_PORT}", "INFO")
    log_message(f"TCP client connecting to {TCP_HOST}:{TCP_PORT}", "INFO")
    log_message(
        f"Messages will be saved after {SAVE_DELAY} seconds of inactivity", "INFO"
    )
    log_message("Daily backup task started", "INFO")

    try:
        await server.wait_closed()
    finally:
        if save_task:
            save_task.cancel()
            try:
                await save_task
            except asyncio.CancelledError:
                pass

        if backup_task:
            backup_task.cancel()
            try:
                await backup_task
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
