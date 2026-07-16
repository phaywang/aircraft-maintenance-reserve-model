"""Dependency-free local HTTP API for the aircraft reserve dashboard."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import build_default_case
from .dashboard_service import case_from_payload, run_dashboard_case
from .scenario_builder import build_scenario_payload, compare_scenario_payloads


class DashboardRunStore:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, object]] = {}

    def create(self, case_payload: dict[str, object]) -> dict[str, object]:
        result = run_dashboard_case(case_from_payload(case_payload))
        run_id = str(result["run"]["run_id"])
        self.runs[run_id] = result
        return result

    def get(self, run_id: str) -> dict[str, object] | None:
        return self.runs.get(run_id)


class DashboardHTTPServer(ThreadingHTTPServer):
    store: DashboardRunStore


class DashboardAPIHandler(BaseHTTPRequestHandler):
    server: DashboardHTTPServer
    max_body_bytes = 1_000_000
    static_root = Path(__file__).resolve().parents[2] / "dashboard" / "static"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "resource_not_found"})

    def _send_static(self, filename: str, content_type: str) -> None:
        path = self.static_root / filename
        if not path.is_file():
            self._not_found()
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _run_section(self, run_id: str, section: str | None) -> None:
        run = self.server.store.get(run_id)
        if run is None:
            self._not_found()
            return
        if section is None:
            self._send_json(
                HTTPStatus.OK,
                {
                    "run": run["run"],
                    "case": run["case"],
                    "summary": run["summary"],
                },
            )
            return
        section_map = {
            "utilization": "utilization",
            "events": "maintenance_calendar",
            "cashflows": "cashflows",
            "funding-risk": "funding_events",
            "audit": "audit",
        }
        key = section_map.get(section)
        if key is None:
            self._not_found()
            return
        self._send_json(HTTPStatus.OK, {key: run[key]})

    def do_OPTIONS(self) -> None:
        self._send_json(HTTPStatus.NO_CONTENT, {})

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path
        static_routes = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/dashboard-data.js": ("dashboard-data.js", "text/javascript; charset=utf-8"),
            "/dashboard-data.json": ("dashboard-data.json", "application/json; charset=utf-8"),
            "/demo-payload.json": ("demo-payload.json", "application/json; charset=utf-8"),
            "/v2": ("../v2/index.html", "text/html; charset=utf-8"),
            "/v2/": ("../v2/index.html", "text/html; charset=utf-8"),
            "/v2/styles.css": ("../v2/styles.css", "text/css; charset=utf-8"),
            "/v2/app.js": ("../v2/app.js", "text/javascript; charset=utf-8"),
            "/v2/dashboard-data.js": ("../v2/dashboard-data.js", "text/javascript; charset=utf-8"),
            "/v2/dashboard-data.json": ("../v2/dashboard-data.json", "application/json; charset=utf-8"),
        }
        if request_path in static_routes:
            self._send_static(*static_routes[request_path])
            return
        parts = [part for part in request_path.split("/") if part]
        if parts == ["api", "health"]:
            self._send_json(
                HTTPStatus.OK,
                {"status": "ok", "calculation_scope": [1, 2, 3, 4]},
            )
            return
        if parts == ["api", "cases", "demo"]:
            self._send_json(HTTPStatus.OK, {"case": build_default_case().to_dict()})
            return
        if parts == ["api", "v2", "demo"]:
            self._send_json(HTTPStatus.OK, build_scenario_payload())
            return
        if len(parts) in (3, 4) and parts[:2] == ["api", "runs"]:
            self._run_section(parts[2], parts[3] if len(parts) == 4 else None)
            return
        self._not_found()

    def do_POST(self) -> None:
        request_path = urlparse(self.path).path
        if request_path not in ("/api/runs", "/api/v2/runs", "/api/v2/compare"):
            self._not_found()
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > self.max_body_bytes:
                raise ValueError("request body is too large")
            raw = self.rfile.read(content_length) if content_length else b"{}"
            request_payload = json.loads(raw)
            if not isinstance(request_payload, dict):
                raise ValueError("request body must be a JSON object")
            if request_path == "/api/v2/runs":
                scenario = request_payload.get("scenario", request_payload)
                if not isinstance(scenario, dict):
                    raise ValueError("scenario must be an object")
                result = build_scenario_payload(scenario)
            elif request_path == "/api/v2/compare":
                scenarios = request_payload.get("scenarios")
                if not isinstance(scenarios, list) or not all(
                    isinstance(item, dict) for item in scenarios
                ):
                    raise ValueError("scenarios must be an array of objects")
                result = compare_scenario_payloads(scenarios)
            else:
                case_payload = request_payload.get("case", request_payload)
                if not isinstance(case_payload, dict):
                    raise ValueError("case must be a JSON object")
                result = self.server.store.create(case_payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_case_inputs", "message": str(exc)},
            )
            return
        self._send_json(HTTPStatus.CREATED, result)


def create_server(host: str = "127.0.0.1", port: int = 8765) -> DashboardHTTPServer:
    server = DashboardHTTPServer((host, port), DashboardAPIHandler)
    server.store = DashboardRunStore()
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aircraft reserve dashboard API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = create_server(args.host, args.port)
    print(f"Dashboard API listening on http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
