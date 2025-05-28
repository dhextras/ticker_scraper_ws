import json
import os
from datetime import UTC, datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

import jwt
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.getenv("USERNAME", "admin")
PASSWORD = os.getenv("PASSWORD", "password123")
JWT_SECRET = os.getenv("JWT_SECRET", "JUST_SOME_RANDOM_FUCKING_KEY-LOL")


class AuthHTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="webinterface", **kwargs)

    def do_POST(self):
        if self.path == "/api/login":
            self.handle_login()
        elif self.path == "/api/verify":
            self.handle_verify()
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        if self.path.startswith("/config.js"):
            if not self.verify_auth():
                (self.verify_auth())
                self.send_error(401, "Unauthorized")
                return

        super().do_GET()

    def handle_login(self):
        try:
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            username = data.get("username")
            password = data.get("password")

            if username == USERNAME and password == PASSWORD:
                payload = {
                    "username": username,
                    "exp": datetime.now(UTC) + timedelta(hours=24),
                }
                token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

                response = {"success": True, "token": token}
                self.send_json_response(200, response)
            else:
                response = {"success": False, "error": "Invalid credentials"}
                self.send_json_response(401, response)

        except Exception as _:
            response = {"success": False, "error": "Server error"}
            self.send_json_response(500, response)

    def handle_verify(self):
        try:
            auth_header = self.headers.get("Authorization")
            print(auth_header)
            if not auth_header or not auth_header.startswith("Bearer "):
                response = {"valid": False}
                self.send_json_response(401, response)
                return

            token = auth_header[7:]

            try:
                _ = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
                response = {"valid": True}
                self.send_json_response(200, response)
            except jwt.ExpiredSignatureError:
                response = {"valid": False, "error": "Token expired"}
                self.send_json_response(401, response)
            except jwt.InvalidTokenError:
                response = {"valid": False, "error": "Invalid token"}
                self.send_json_response(401, response)

        except Exception as _:
            response = {"valid": False, "error": "Server error"}
            self.send_json_response(500, response)

    def verify_auth(self):
        auth_header = self.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return False

        token = auth_header[7:]  # Remove 'Bearer ' prefix

        try:
            _ = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            return True
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return False

    def send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

        json_data = json.dumps(data)
        self.wfile.write(json_data.encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""

    daemon_threads = True


def run_server(port=80):
    server_address = ("", port)
    httpd = ThreadedHTTPServer(server_address, AuthHTTPRequestHandler)
    print(f"Server running on port {port}")
    print(f"Username: {USERNAME}")
    print(f"Password: {PASSWORD}")
    httpd.serve_forever()


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    run_server(port)
