#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
from pathlib import Path

from flask import Flask, request, jsonify
import paramiko

app = Flask(__name__)

SSH_USER = os.getenv("YOCTO_SSH_USER", "mark")
SSH_HOST = os.getenv("YOCTO_SSH_HOST", "192.168.1.142")
SSH_KEY = Path(os.getenv("YOCTO_SSH_KEY", Path.home() / ".ssh" / "id_rsa"))
REMOTE_BASE = os.getenv("YOCTO_REMOTE_BASE", f"/home/{SSH_USER}/Hiner.nyc/yocto")
REMOTE_SCRIPT = f"{REMOTE_BASE}/hotel_search_web.py"
REMOTE_RESULTS = f"{REMOTE_BASE}/results.html"
LOCAL_RESULTS = Path(__file__).resolve().parent / "results.html"


def run_remote(where: str, check_in: str, check_out: str) -> None:
    key = paramiko.RSAKey.from_private_key_file(str(SSH_KEY))
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, username=SSH_USER, pkey=key)

    cmd = (
        f"python3 {shlex.quote(REMOTE_SCRIPT)} "
        f"--city {shlex.quote(where)} "
        f"--check-in {shlex.quote(check_in)} "
        f"--check-out {shlex.quote(check_out)} "
        f"--out {shlex.quote(REMOTE_RESULTS)}"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        raise RuntimeError(stderr.read().decode())

    sftp = ssh.open_sftp()
    sftp.get(REMOTE_RESULTS, str(LOCAL_RESULTS))
    sftp.close()
    ssh.close()


@app.post("/yocto/run_search")
def handle_search():
    data = request.get_json(force=True)
    where = data.get("where", "")
    check_in = data.get("check_in")
    check_out = data.get("check_out")
    try:
        run_remote(where, check_in, check_out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)