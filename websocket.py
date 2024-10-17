import asyncio
import websockets
import json
import os
from datetime import datetime

# File to store messages
MESSAGES_FILE = 'messages.json'

# Load messages from JSON file
def load_messages_from_json():
    if os.path.exists(MESSAGES_FILE):
        with open(MESSAGES_FILE, 'r') as file:
            return json.load(file)
    return []

# Save message to JSON file
def save_message_to_json(sender, message_type, content):
    # Load existing messages
    messages = load_messages_from_json()
    
    # Append new message with current timestamp
    messages.append({
        "sender": sender,
        "type": message_type,
        "content": content,
        "timestamp": datetime.now().isoformat()  # Use current time in ISO format
    })
    
    # Write back to the JSON file
    with open(MESSAGES_FILE, 'w') as file:
        json.dump(messages, file, indent=4)

# Store connected clients
connected_clients = set()

# WebSocket server handler
async def handler(websocket, path):
    print("Client connected")
    connected_clients.add(websocket)  # Add the client to the connected clients set

    try:
        # Send all previous messages to the new client when they connect
        old_messages = load_messages_from_json()
        for msg in old_messages:
            await websocket.send(json.dumps(msg))

        async for message in websocket:
            data = json.loads(message)
            sender = data.get("sender", "Unknown")
            message_type = data.get("type", "default")
            content = data.get("content", "")

            print(f"Received message from {sender} - Type: {message_type}, Content: {content}")

            # Save the client's message to the JSON file
            save_message_to_json(sender, message_type, content)

            # Broadcast the message to all connected clients (including sender)
            broadcast_message = json.dumps({
                "sender": sender,
                "type": message_type,
                "content": content,
                "timestamp": datetime.now().isoformat()  # Add the current timestamp
            })

            # Broadcast the message to all connected clients
            await asyncio.gather(
                *[client.send(broadcast_message) for client in connected_clients]
            )

    except websockets.ConnectionClosed as e:
        print(f"Client disconnected: {e}")
    finally:
        connected_clients.remove(websocket)  # Remove the client when disconnected

# Start the WebSocket server with custom ping_interval and ping_timeout
async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080, ping_interval=None, ping_timeout=None):
        print("WebSocket server running on ws://0.0.0.0:8080")
        await asyncio.Future()  # Keep the server running

if __name__ == "__main__":
    asyncio.run(main())
