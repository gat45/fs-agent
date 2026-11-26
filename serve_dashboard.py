"""Serveur HTTP simple pour le dashboard FS-Agent."""
import http.server
import socketserver
import os
import sys
import threading
import webbrowser

PORT = 8765
DIR = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def log_message(self, format, *args):
        pass  # Silencieux


def start_server(port=PORT, open_browser=True):
    os.chdir(DIR)
    with socketserver.TCPServer(("", port), Handler) as httpd:
        url = f"http://localhost:{port}/dashboard.html"
        print(f"Dashboard disponible sur: {url}")
        if open_browser:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        httpd.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    start_server(port)