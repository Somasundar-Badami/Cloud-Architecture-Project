"""
dashboard/dev_server.py -- run the dashboard locally with NO AWS account.

Starts moto's in-memory AWS, builds the same three monitored resources and
pipeline tables the Terraform deploys (reusing the builder from
tests/test_drift_pipeline.py), runs one clean scan, makes three
out-of-band changes (S1 / E1 / I6), runs a second scan, and then serves:

    http://localhost:8765/            dashboard/index.html
    /config.js                        local config (overrides the Terraform one)
    /cognito                          fake sign-in: any email/password works
    /api/<route>                      the REAL lambda_api / lambda_detector handlers

Everything shown is computed by the real pipeline code; only AWS itself is
simulated. Labelled "LOCAL DEMO" in the page title so it is never mistaken
for the deployed system.

    python dashboard/dev_server.py
"""

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

PORT = int(os.environ.get("PORT", "8765"))
for key, value in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                   "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": "us-east-1"}.items():
    os.environ[key] = value

from moto import mock_aws  # noqa: E402

MOCK = mock_aws()
MOCK.start()

import lambda_api  # noqa: E402
import lambda_detector  # noqa: E402
import test_drift_pipeline as fixtures  # noqa: E402


class _Env:
    @staticmethod
    def setenv(key, value):
        os.environ[key] = value


def build_demo_account():
    env = fixtures._build_account(_Env())
    lambda_detector.handler({"trigger": "local-demo"}, None)
    fixtures._inject_drift(env)
    lambda_detector.handler({"trigger": "local-demo"}, None)
    return env


LOCAL_CONFIG = (
    "window.DRIFT_CONFIG = "
    + json.dumps({"region": "us-east-1", "apiUrl": "/api", "clientId": "local-demo", "cognitoEndpoint": "/cognito"})
    + ";\ndocument.title = 'LOCAL DEMO - ' + document.title;\n"
)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def _send_json(self, status, body):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api(self, method):
        url = urlparse(self.path)
        route = f"{method} {url.path[len('/api'):]}"
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else None
        if route == "POST /scan":  # no Lambda service locally -> call the detector directly
            return self._send_json(200, lambda_detector.handler({"trigger": "api"}, None))
        resp = lambda_api.handler({"routeKey": route, "body": body,
                                   "queryStringParameters": dict(parse_qsl(url.query)) or None}, None)
        self._send_json(resp["statusCode"], resp["body"])

    def do_GET(self):
        if self.path == "/config.js":
            data = LOCAL_CONFIG.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if self.path.startswith("/api/"):
            return self._api("GET")
        return super().do_GET()

    def do_POST(self):
        if self.path == "/cognito":
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self._send_json(200, {"AuthenticationResult": {"AccessToken": "local-demo-token"}})
        if self.path.startswith("/api/"):
            return self._api("POST")
        self._send_json(404, {"error": "not found"})


if __name__ == "__main__":
    build_demo_account()
    print(f"LOCAL DEMO (moto, no real AWS): http://localhost:{PORT}/  -- any email/password signs in")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
