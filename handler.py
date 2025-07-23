

import time
import json

class Handler:
    def __init__(self, timer_state, queue, current_task_index, save_queue_func):
        self.timer_state = timer_state
        self.queue = queue
        self.current_task_index = current_task_index
        self.save_queue = save_queue_func

    def handle(self, parts):
        cmd = parts[0].lower()
        if cmd == "start":
            duration = int(parts[1]) if len(parts) > 1 else 300
            self.handle_start(duration)
        elif cmd == "pause":
            self.handle_pause()
        elif cmd == "resume":
            self.handle_resume()
        elif cmd == "reset":
            self.handle_reset()
        elif cmd == "queue_add":
            if len(parts) >= 3:
                name = parts[1]
                duration = int(parts[2])
                self.handle_queue_add(name, duration)
        elif cmd == "adjust":
            if len(parts) > 1:
                try:
                    delta = int(parts[1])
                    self.handle_adjust(delta)
                except Exception:
                    pass
        elif cmd == "queue_clear":
            self.handle_queue_clear()
        elif cmd == "next":
            self.handle_queue_next()
        elif cmd == "prev":
            self.handle_queue_previous()

    def handle_start(self, duration):
        self.timer_state["duration"] = duration
        self.timer_state["start_time"] = time.time()
        self.timer_state["running"] = True

    def handle_pause(self):
        if self.timer_state["running"]:
            elapsed = time.time() - self.timer_state["start_time"]
            self.timer_state["remaining"] = int(self.timer_state["duration"] - elapsed)
            self.timer_state["running"] = False

    def handle_resume(self):
        self.timer_state["start_time"] = time.time() - (self.timer_state["duration"] - self.timer_state["remaining"])
        self.timer_state["running"] = True

    def handle_reset(self):
        self.timer_state["running"] = False
        self.timer_state["remaining"] = self.timer_state["duration"]

    def handle_queue_add(self, name, duration):
        self.queue.append({"name": name, "duration": duration})
        self.save_queue(self.queue)

    def handle_adjust(self, delta):
        self.timer_state["remaining"] += delta
        if self.timer_state["running"]:
            self.timer_state["start_time"] = time.time() - (self.timer_state["duration"] - self.timer_state["remaining"])

    def handle_queue_clear(self):
        self.queue.clear()
        self.save_queue(self.queue)
        self.current_task_index[0] = 0

    def handle_queue_next(self):
        if self.queue and self.current_task_index[0] < len(self.queue) - 1:
            self.current_task_index[0] += 1
            task = self.queue[self.current_task_index[0]]
            self.timer_state["duration"] = task["duration"]
            self.timer_state["remaining"] = task["duration"]
            self.timer_state["running"] = False
            self.save_queue(self.queue)

    def handle_queue_previous(self):
        if self.queue and self.current_task_index[0] > 0:
            self.current_task_index[0] -= 1
            task = self.queue[self.current_task_index[0]]
            self.timer_state["duration"] = task["duration"]
            self.timer_state["remaining"] = task["duration"]
            self.timer_state["running"] = False
            self.save_queue(self.queue)


