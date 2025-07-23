############################################################
# server.py
# A WebSocket-based timer server for stage management,
# supporting a queue of timed tasks.
# Clients can control the timer and queue via commands.
############################################################

# --- Imports ---

import asyncio
import websockets
import json
import time
from handler import Handler
import http.server
import socketserver
import threading
import os


# --- Global State ---
clients = set()  # Set of connected WebSocket clients
timer_state = {
    "duration": 300,      # seconds (5 minutes default)
    "start_time": None,   # Timestamp when timer started
    "running": False,     # Is the timer running?
    "remaining": 300      # Remaining time in seconds (can go negative)
}


# --- Queue Management (persistent to file) ---
import os
QUEUE_FILE = "queue.json"


def load_queue():
    """Load the queue from a JSON file (UTF-8)."""
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_queue(queue):
    """Save the queue to a JSON file (UTF-8)."""
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False)



# --- Initialize queue and current task index ---

queue = load_queue()
# Use a list for current_task_index to allow mutation in Handler
current_task_index = [0]


# On server start, if queue exists, load first task as timer (not running)

if queue:
    timer_state["duration"] = queue[0]["duration"]
    timer_state["remaining"] = queue[0]["duration"]
    timer_state["running"] = False



# --- Notify all clients of timer/queue state every second ---
async def notify_clients():
    while True:
        if timer_state["running"]:
            # Update remaining time (can go negative)
            elapsed = time.time() - timer_state["start_time"]
            remaining = timer_state["duration"] - elapsed
            timer_state["remaining"] = int(remaining)
        # Prepare state message
        # Add current task name if available
        current_name = ""
        idx = current_task_index[0] if isinstance(current_task_index, list) else current_task_index
        if queue and 0 <= idx < len(queue):
            current_name = queue[idx].get("name", "")
        message = json.dumps({
            "remaining": timer_state["remaining"],
            "running": timer_state["running"],
            "queue": queue,
            "current_task_index": idx,
            "current_name": current_name
        })
        # Send to all connected clients
        disconnected = set()
        for client in clients:
            try:
                await client.send(message)
            except Exception:
                disconnected.add(client)
        # Remove disconnected clients
        for client in disconnected:
            clients.discard(client)
        await asyncio.sleep(1)


# --- WebSocket handler for each client ---

async def handler(websocket):
    clients.add(websocket)
    handler_obj = Handler(timer_state, queue, current_task_index, save_queue)
    try:
        async for message in websocket:
            parts = message.strip().split()
            handler_obj.handle(parts)

        # On connect, send current state immediately
        idx = current_task_index[0] if isinstance(current_task_index, list) else current_task_index
        current_name = ""
        if queue and 0 <= idx < len(queue):
            current_name = queue[idx].get("name", "")
        await websocket.send(json.dumps({
            "remaining": timer_state["remaining"],
            "running": timer_state["running"],
            "queue": queue,
            "current_task_index": idx,
            "current_name": current_name
        }))
    finally:
        clients.remove(websocket)


# --- HTTP Server for serving HTML files ---
def start_http_server():
    """Start HTTP server on port 8000 to serve HTML files."""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # Change to script directory
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", 8000), handler) as httpd:
        print("HTTP server serving at http://localhost:8000")
        httpd.serve_forever()


# --- Main entry point: start WebSocket server and notification loop ---
async def main():
    # Start HTTP server in a separate thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    print("WebSocket server starting on ws://localhost:50011")
    
    async with websockets.serve(handler, "", 50011):
        await notify_clients()

asyncio.run(main())
