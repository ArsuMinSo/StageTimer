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
import logging

# Silence noisy tracebacks the websockets library logs whenever something
# opens a raw TCP connection to the WS port and closes it without completing
# a handshake (port scans, health checks, aborted browser connections). These
# are harmless and don't affect the running server.
logging.getLogger("websockets.server").setLevel(logging.CRITICAL)


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
TIMER_STATE_FILE = "timer_state.json"


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


def load_timer_state():
    """Load the timer state from a JSON file."""
    if os.path.exists(TIMER_STATE_FILE):
        try:
            with open(TIMER_STATE_FILE, "r", encoding="utf-8") as f:
                saved_state = json.load(f)
                # Don't restore running state - always start paused
                saved_state["running"] = False
                saved_state["start_time"] = None
                return saved_state
        except Exception as e:
            print(f"Error loading timer state: {e}")
    return {
        "duration": 300,
        "start_time": None,
        "running": False,
        "remaining": 300
    }


def save_timer_state():
    """Save the current timer state to a JSON file."""
    try:
        # Create a copy without start_time for JSON serialization
        state_to_save = {
            "duration": timer_state["duration"],
            "remaining": timer_state["remaining"],
            "running": False,  # Always save as not running
            "start_time": None
        }
        with open(TIMER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state_to_save, f, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving timer state: {e}")



# --- Initialize queue and current task index ---

queue = load_queue()
# Use a list for current_task_index to allow mutation in Handler
current_task_index = [0]

# Load previous timer state
timer_state = load_timer_state()

# On server start, if queue exists and no saved state, load first task as timer
if queue and timer_state["duration"] == 300 and timer_state["remaining"] == 300:
    timer_state["duration"] = queue[0]["duration"]
    timer_state["remaining"] = queue[0]["duration"]
    timer_state["running"] = False



# --- Notify all clients of timer/queue state every second ---
async def notify_clients():
    while True:
        try:
            if timer_state["running"]:
                # Update remaining time (can go negative)
                elapsed = time.time() - timer_state["start_time"]
                remaining = timer_state["duration"] - elapsed
                timer_state["remaining"] = int(remaining)
            
            # Save timer state every second
            save_timer_state()
            
            # Prepare state message
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
            for client in clients.copy():  # Use copy to avoid modification during iteration
                try:
                    await client.send(message)
                except websockets.exceptions.ConnectionClosed:
                    disconnected.add(client)
                except Exception as e:
                    print(f"Error sending to client: {e}")
                    disconnected.add(client)
            
            # Remove disconnected clients
            for client in disconnected:
                clients.discard(client)
                
        except Exception as e:
            print(f"Error in notify_clients: {e}")
        
        await asyncio.sleep(1)


# --- WebSocket handler for each client ---

async def handler(websocket):
    clients.add(websocket)
    handler_obj = Handler(timer_state, queue, current_task_index, save_queue)
    try:
        # Send current state immediately on connect
        idx = current_task_index[0] if isinstance(current_task_index, list) else current_task_index
        current_name = ""
        if queue and 0 <= idx < len(queue):
            current_name = queue[idx].get("name", "")
        
        initial_message = json.dumps({
            "remaining": timer_state["remaining"],
            "running": timer_state["running"],
            "queue": queue,
            "current_task_index": idx,
            "current_name": current_name
        })
        
        await websocket.send(initial_message)
        
        # Handle incoming messages
        async for message in websocket:
            try:
                stripped = message.strip()
                if not stripped:
                    continue
                if stripped.startswith("{"):
                    # JSON commands carry free-text fields (e.g. task names with spaces)
                    handler_obj.handle_json(json.loads(stripped))
                else:
                    handler_obj.handle(stripped.split())
            except Exception as e:
                print(f"Error handling message '{message}': {e}")
                
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
    except Exception as e:
        print(f"Handler error: {e}")
    finally:
        clients.discard(websocket)  # Use discard instead of remove to avoid KeyError


# --- HTTP Server for serving HTML files ---
def start_http_server():
    """Start HTTP server on port 50012 to serve HTML files."""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # Change to script directory
    
    class CustomHandler(http.server.SimpleHTTPRequestHandler):
        def do_POST(self):
            if self.path == '/save-page':
                # Handle saving custom HTML pages
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(post_data)
                
                filename = data.get('filename', 'custom.html')
                content = data.get('content', '')

                # Sanitize filename: strip any directory components and
                # only allow writing .html files into the script directory,
                # to prevent path traversal to arbitrary filesystem locations.
                filename = os.path.basename(filename)
                if not filename.endswith('.html') or filename in ('', '.html'):
                    self.send_response(400)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Invalid filename'}).encode())
                    return

                # Save the file
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(content)

                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({'success': True}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': str(e)}).encode())
            else:
                self.send_response(404)
                self.end_headers()
    
    # Add socket reuse option to prevent "Address already in use" error
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True
    
    try:
        with ReusableTCPServer(("0.0.0.0", 50012), CustomHandler) as httpd:
            print("HTTP server serving at http://0.0.0.0:50012")
            httpd.serve_forever()
    except OSError as e:
        if e.errno == 98:  # Address already in use
            print("Error: Port 50012 is already in use. Trying port 50013...")
            try:
                with ReusableTCPServer(("0.0.0.0", 50013), CustomHandler) as httpd:
                    print("HTTP server serving at http://0.0.0.0:50013")
                    httpd.serve_forever()
            except OSError:
                print("Error: Both ports 50012 and 50013 are in use. Please free up these ports.")
        else:
            raise e


# --- Main entry point: start WebSocket server and notification loop ---
async def main():
    try:
        # Start HTTP server in a separate thread
        http_thread = threading.Thread(target=start_http_server, daemon=True)
        http_thread.start()
        print("WebSocket server starting on ws://0.0.0.0:50011")
        
        async with websockets.serve(handler, "0.0.0.0", 50011):
            await notify_clients()
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Server error: {e}")
        print("Restarting in 5 seconds...")
        await asyncio.sleep(5)
        await main()  # Restart

if __name__ == "__main__":
    asyncio.run(main())
