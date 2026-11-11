#!/usr/bin/env python3
"""Run inside a KubeSpawner Workspace Pod."""
import json
import os
import socket
import time
from pathlib import Path

import requests
import websocket
from jupyter_client import BlockingKernelClient


hostname = socket.gethostname()
prefix = os.environ["JUPYTERHUB_SERVICE_PREFIX"].rstrip("/")
base = f"http://127.0.0.1:8888{prefix}/api"
headers = {"Authorization": f"token {os.environ['JUPYTERHUB_API_TOKEN']}"}

for forbidden in ("OAUTH_CLIENT_SECRET", "HUB_ADMIN_TOKEN", "UEM_COLLECTOR_TOKEN"):
    assert forbidden not in os.environ, f"platform secret leaked: {forbidden}"
assert not Path("/var/run/secrets/kubernetes.io/serviceaccount/token").exists()
print("PASS platform secrets and Kubernetes ServiceAccount token are absent")

kernel = requests.post(f"{base}/kernels", headers=headers, json={"name": "python3"}, timeout=20)
kernel.raise_for_status()
kernel_id = kernel.json()["id"]

terminal = requests.post(f"{base}/terminals", headers=headers, json={}, timeout=20)
terminal.raise_for_status()
terminal_name = terminal.json()["name"]

try:
    connection_file = Path.home() / ".local/share/jupyter/runtime" / f"kernel-{kernel_id}.json"
    for _ in range(100):
        if connection_file.exists():
            break
        time.sleep(0.1)
    assert connection_file.exists()

    client = BlockingKernelClient(connection_file=str(connection_file))
    client.load_connection_file()
    client.start_channels()
    client.wait_for_ready(timeout=15)
    message_id = client.execute(
        "import socket, getpass; "
        "print('WORKSPACE_KERNEL_OK:'+socket.gethostname()+':'+getpass.getuser())"
    )
    kernel_output = ""
    while True:
        message = client.get_iopub_msg(timeout=15)
        if message["parent_header"].get("msg_id") != message_id:
            continue
        if message["msg_type"] == "stream":
            kernel_output += message["content"]["text"]
        if message["msg_type"] == "status" and message["content"]["execution_state"] == "idle":
            break
    client.stop_channels()
    assert f"WORKSPACE_KERNEL_OK:{hostname}:jovyan" in kernel_output
    print(kernel_output.strip())

    ws = websocket.create_connection(
        f"ws://127.0.0.1:8888{prefix}/terminals/websocket/{terminal_name}",
        header=[headers["Authorization"].replace("token ", "Authorization: token ", 1)],
        origin="http://127.0.0.1:8888",
        timeout=2,
    )
    ws.send(json.dumps(["stdin", "echo WORKSPACE_TERMINAL_OK:$HOSTNAME:$(id -un)\r"]))
    terminal_output = ""
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        if message and message[0] == "stdout":
            terminal_output += message[1]
            if f"WORKSPACE_TERMINAL_OK:{hostname}:jovyan" in terminal_output:
                break
    ws.close()
    assert f"WORKSPACE_TERMINAL_OK:{hostname}:jovyan" in terminal_output
    print(f"WORKSPACE_TERMINAL_OK:{hostname}:jovyan")
finally:
    requests.delete(f"{base}/terminals/{terminal_name}", headers=headers, timeout=20)
    requests.delete(f"{base}/kernels/{kernel_id}", headers=headers, timeout=20)
