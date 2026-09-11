"""Bounded accepted-connection ownership, including slow request deadlines."""
import socket
import threading
import time
from http.server import ThreadingHTTPServer


class DashboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True
    request_deadline = 5.0
    max_connections = 16

    def __init__(self, *args, **kwargs):
        self.active = threading.Event()
        self.active.set()
        self.guard = threading.Lock()
        self.connections = {}
        self.handlers = []
        super().__init__(*args, **kwargs)
        self.watchdog = threading.Thread(target=self._watch, name='lan-deadlines', daemon=True)
        self.watchdog.start()

    @staticmethod
    def abort(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    def process_request(self, request, client_address):
        with self.guard:
            if not self.active.is_set() or len(self.connections) >= self.max_connections:
                self.abort(request)
                return
            request.settimeout(min(.5, self.request_deadline))
            self.connections[request] = time.monotonic() + self.request_deadline
            thread = threading.Thread(target=self.process_request_thread,
                                      args=(request, client_address), name='lan-client', daemon=True)
            self.handlers = [item for item in self.handlers if item.is_alive()]
            self.handlers.append(thread)
            thread.start()

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.guard:
                self.connections.pop(request, None)

    def handle_error(self, request, client_address):
        # Disconnects and deadline cancellation are expected lifecycle events.
        pass

    def _watch(self):
        while self.active.is_set():
            with self.guard:
                expired = [sock for sock, deadline in self.connections.items() if time.monotonic() >= deadline]
            for sock in expired:
                self.abort(sock)
            time.sleep(.05)

    def revoke(self):
        self.active.clear()
        with self.guard:
            sockets = list(self.connections)
        for sock in sockets:
            self.abort(sock)

    def join_clients(self, timeout=2):
        deadline = time.monotonic() + timeout
        for thread in [self.watchdog] + self.handlers:
            if thread is not threading.current_thread():
                thread.join(max(0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in [self.watchdog] + self.handlers)
