#!/usr/bin/env python3
"""Run inside a kernel pod. Exits non-zero when an isolation invariant fails."""
import json
import os
import socket
import sys
import urllib.error
import urllib.request

BASE = os.getenv("UEM_COLLECTOR_URL", "http://uem-collector:8080")
TOKEN = os.getenv("UEM_COLLECTOR_TOKEN", "mock-kernel-session-token")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json", "X-Trace-Id": "automated-smoke"}
failures = []


def call(path, body, expected=200):
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, payload = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read().decode()
    print(f"{path}: {status} {payload[:200]}")
    if status != expected:
        failures.append(f"{path}: expected {expected}, got {status}")


call("/v1/uem/events", {"event": "cell_execute_end", "session_id": "smoke", "attributes": {"code": "secret"}}, 422)

for host, port in (("mock-postgres", 5432), ("mock-mysql", 3306), ("mock-mongo", 27017), ("mock-elasticsearch", 9200)):
    try:
        socket.create_connection((host, port), 2).close()
        failures.append(f"network policy bypass: {host}:{port} is reachable")
        print(f"DIRECT_REACHABLE {host}:{port}")
    except OSError:
        print(f"DIRECT_BLOCKED {host}:{port}")

if failures:
    print("FAILURES:")
    print("\n".join(f"- {failure}" for failure in failures))
    sys.exit(1)
print("ALL INVARIANTS PASSED")
