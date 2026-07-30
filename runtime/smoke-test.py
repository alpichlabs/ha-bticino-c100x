#!/usr/bin/env python3
"""Offline amd64 runtime smoke test: checksum, extraction and IPC hello only."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("sha256")
    args = parser.parse_args()
    if hashlib.sha256(args.archive.read_bytes()).hexdigest() != args.sha256:
        raise SystemExit("checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="c100x-runtime-") as temporary:
        root = Path(temporary)
        with tarfile.open(args.archive, "r:gz") as package:
            package.extractall(root, filter="data")
        control = root / "control.sock"
        process = subprocess.Popen(
            [root / "bin" / "bticino-c100x-linphone", "--socket", control],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(100):
                if control.exists():
                    break
                if process.poll() is not None:
                    error = process.stderr.read().decode(errors="replace")[-1000:]
                    raise SystemExit("runtime exited: " + error)
                time.sleep(0.05)
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(str(control))
                reader = client.makefile("rb")
                client.sendall(b'{"id":1,"command":"hello"}\n')
                response = json.loads(reader.readline())
                assert response == {
                    "id": 1,
                    "protocol": 1,
                    "version": "0.1.0",
                    "linphone": "5.4",
                }
                client.sendall(b'{"id":2,"command":"self_test"}\n')
                self_test = json.loads(reader.readline())
                if self_test != {"id": 2, "binding": "ok", "missing": []}:
                    raise AssertionError(f"unexpected self-test response: {self_test!r}")
                client.sendall(b'{"id":3,"command":"shutdown"}\n')
                shutdown = json.loads(reader.readline())
                assert shutdown == {"id": 3}
                reader.close()
            if process.wait(timeout=5) != 0:
                raise SystemExit("runtime shutdown failed")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
    print("Linphone runtime offline smoke test passed")


if __name__ == "__main__":
    main()
