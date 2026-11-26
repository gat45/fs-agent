"""Serveur HTTP avec API pour le dashboard FS-Agent interactif."""
import http.server
import socketserver
import os
import sys
import json
import threading
import subprocess
import signal
from pathlib import Path

PORT = 8766
DIR = os.path.dirname(os.path.abspath(__file__))
SCAN_PROCESS = None
PROGRESS_FILE = os.path.join(DIR, "progress.json")


class APIHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_GET(self):
        if self.path == "/api/status":
            self._json_response(self._get_status())
        elif self.path.startswith("/api/progress"):
            self._json_response(self._get_progress())
        elif self.path.startswith("/api/browse"):
            self._json_response(self._browse(self.path))
        elif self.path == "/":
            self.path = "/dashboard.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        if self.path == "/api/start":
            self._json_response(self._start_scan(data))
        elif self.path == "/api/stop":
            self._json_response(self._stop_scan())
        else:
            self.send_error(404)

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _get_progress(self):
        try:
            if os.path.exists(PROGRESS_FILE):
                with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"phase": "idle", "total_files": 0, "total_dirs": 0, "total_size": 0, "errors": 0, "by_drive": {}, "last_message": "En attente..."}

    def _get_status(self):
        global SCAN_PROCESS
        if SCAN_PROCESS is not None:
            poll = SCAN_PROCESS.poll()
            if poll is None:
                return {"running": True, "pid": SCAN_PROCESS.pid}
            else:
                SCAN_PROCESS = None
                return {"running": False, "exit_code": poll}
        return {"running": False}

    def _browse(self, path):
        """Liste les dossiers d'un chemin pour le selecteur."""
        import urllib.parse
        parsed = urllib.parse.urlparse(path)
        params = urllib.parse.parse_qs(parsed.query)
        browse_path = params.get("path", [""])[0]

        if not browse_path:
            # Racine: lister les disques
            drives = []
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                p = f"{letter}:\\"
                if os.path.exists(p) and os.path.isdir(p):
                    drives.append({"name": f"{letter}:", "path": p, "type": "drive"})
            return {"path": "", "items": drives}

        if not os.path.exists(browse_path) or not os.path.isdir(browse_path):
            return {"error": "Chemin invalide", "path": browse_path, "items": []}

        items = []
        try:
            for entry in sorted(os.scandir(browse_path), key=lambda e: e.name.lower()):
                if entry.is_dir(follow_symlinks=False):
                    items.append({"name": entry.name, "path": entry.path, "type": "dir"})
        except PermissionError:
            return {"error": "Acces refuse", "path": browse_path, "items": []}
        except Exception as e:
            return {"error": str(e), "path": browse_path, "items": []}

        # Limiter a 100 entrees
        items = items[:100]
        return {"path": browse_path, "items": items, "parent": os.path.dirname(browse_path) if browse_path not in ("", "\\") else None}
        try:
            if os.path.exists(PROGRESS_FILE):
                with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"phase": "idle", "total_files": 0, "total_dirs": 0, "total_size": 0, "errors": 0, "by_drive": {}, "last_message": "En attente..."}

    def _start_scan(self, data):
        global SCAN_PROCESS
        if SCAN_PROCESS is not None and SCAN_PROCESS.poll() is None:
            return {"error": "Un scan est deja en cours"}

        roots = data.get("roots", [])
        if not roots:
            # Detecter tous les disques
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                path = f"{letter}:\\"
                if os.path.exists(path) and os.path.isdir(path):
                    roots.append(path)

        if not roots:
            return {"error": "Aucun disque detecte"}

        # Construire la commande
        cmd = [sys.executable, "cli.py"] + roots
        if data.get("partial_only"):
            cmd.append("--partial-only")
        if data.get("no_hash"):
            cmd.append("--no-hash")
        if data.get("max_depth"):
            cmd.extend(["--max-depth", str(data["max_depth"])])
        if data.get("workers"):
            cmd.extend(["--workers", str(data["workers"])])
        if data.get("sequential"):
            cmd.append("--sequential")
        if data.get("io_threads"):
            cmd.extend(["--io-threads", str(data["io_threads"])])
        if data.get("dashboard"):
            cmd.append("--dashboard")

        # Fichier de progression
        cmd.extend(["--progress-file", PROGRESS_FILE])

        # Output dir
        out_dir = data.get("output", os.path.join(DIR, "reports"))
        cmd.extend(["--output", out_dir])

        # Lancer le scan
        try:
            SCAN_PROCESS = subprocess.Popen(cmd, cwd=DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"started": True, "pid": SCAN_PROCESS.pid, "roots": roots, "cmd": " ".join(cmd)}
        except Exception as e:
            return {"error": str(e)}

    def _stop_scan(self):
        global SCAN_PROCESS
        if SCAN_PROCESS is not None:
            try:
                SCAN_PROCESS.terminate()
                SCAN_PROCESS.wait(timeout=5)
            except Exception:
                SCAN_PROCESS.kill()
            SCAN_PROCESS = None
            return {"stopped": True}
        return {"error": "Aucun scan en cours"}

    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def start_server(port=PORT):
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", port), APIHandler) as httpd:
        print(f"Serveur API disponible sur: http://localhost:{port}")
        print(f"Dashboard: http://localhost:{port}/dashboard.html")
        httpd.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    start_server(port)