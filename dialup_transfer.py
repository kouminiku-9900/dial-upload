#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import random
import socket
import sys
import threading
import time
from pathlib import Path

BUFFER_SIZE = 4096
PROTOCOL_VERSION = 1


class DialupFX:
    STAGES = [
        "ATZ",
        "OK",
        "ATDT 9,***,****",
        "CONNECT 56000",
        "PPP LCP negotiation...",
        "PPP authentication...",
        "IPCP complete.",
    ]

    @staticmethod
    def startup(host: str, port: int) -> None:
        print("=" * 56)
        print(" Retro Dial-Up Transfer v0.1 ")
        print("=" * 56)
        print(f" Listening on {host}:{port}")
        print("\n[MODEM] Handshake sequence")
        for stage in DialupFX.STAGES:
            time.sleep(random.uniform(0.15, 0.45))
            print(f"  {stage}")
        print("  *Static noise* krrrrk-chi-chi-bzzzt")
        print("  Line established. Ready for transfer.\n")

    @staticmethod
    def blip() -> None:
        sys.stdout.write("\a")
        sys.stdout.flush()


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(BUFFER_SIZE, size - len(data)))
        if not chunk:
            raise ConnectionError("connection closed while receiving data")
        data.extend(chunk)
    return bytes(data)


def recv_line(sock: socket.socket) -> bytes:
    data = bytearray()
    while True:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("connection closed while receiving header")
        if ch == b"\n":
            return bytes(data)
        data.extend(ch)


def throttle_sleep(chunk_size: int, kbps: float, chaos: bool) -> None:
    if kbps <= 0:
        return
    bytes_per_sec = (kbps * 1000.0) / 8.0
    delay = chunk_size / bytes_per_sec
    if chaos:
        delay *= random.uniform(0.6, 1.7)
        if random.random() < 0.03:
            delay += random.uniform(0.3, 1.2)
    time.sleep(delay)


def progress(prefix: str, transferred: int, total: int, started: float) -> None:
    elapsed = max(time.time() - started, 1e-6)
    kbps = (transferred * 8.0 / 1000.0) / elapsed
    ratio = transferred / total if total else 1
    bar_len = 24
    filled = int(bar_len * ratio)
    bar = "#" * filled + "-" * (bar_len - filled)
    sys.stdout.write(
        f"\r{prefix} [{bar}] {ratio * 100:6.2f}%  {kbps:6.2f} kbps  {transferred}/{total} bytes"
    )
    sys.stdout.flush()


def send_file(host: str, port: int, file_path: Path, kbps: float, chaos: bool) -> None:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"file not found: {file_path}")

    file_size = file_path.stat().st_size
    checksum = sha256sum(file_path)
    header = {
        "version": PROTOCOL_VERSION,
        "filename": file_path.name,
        "size": file_size,
        "sha256": checksum,
    }

    print(f"[SENDER] Dialing {host}:{port}...")
    with socket.create_connection((host, port), timeout=20) as sock:
        line = json.dumps(header).encode("utf-8") + b"\n"
        sock.sendall(line)

        started = time.time()
        transferred = 0
        with file_path.open("rb") as f:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)
                transferred += len(chunk)
                progress("[SEND]", transferred, file_size, started)
                throttle_sleep(len(chunk), kbps, chaos)
                if chaos and random.random() < 0.04:
                    DialupFX.blip()

        ack = recv_line(sock).decode("utf-8", errors="replace")
        print()
        if ack == "OK":
            print("[SENDER] Transfer complete. Receiver checksum OK.")
        else:
            print(f"[SENDER] Receiver reported error: {ack}")


def handle_client(conn: socket.socket, addr: tuple[str, int], out_dir: Path, kbps: float, chaos: bool) -> None:
    try:
        print(f"\n[RECV] Incoming call from {addr[0]}:{addr[1]}")
        header_line = recv_line(conn)
        header = json.loads(header_line.decode("utf-8"))

        if header.get("version") != PROTOCOL_VERSION:
            conn.sendall(b"ERR unsupported protocol version\n")
            print("[RECV] Unsupported protocol version")
            return

        filename = os.path.basename(header["filename"])
        total_size = int(header["size"])
        expected_sha = str(header["sha256"])

        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / filename
        stem, suffix = target.stem, target.suffix
        n = 1
        while target.exists():
            target = out_dir / f"{stem}_{n}{suffix}"
            n += 1

        started = time.time()
        received = 0
        h = hashlib.sha256()
        with target.open("wb") as f:
            while received < total_size:
                chunk = conn.recv(min(BUFFER_SIZE, total_size - received))
                if not chunk:
                    raise ConnectionError("connection lost during transfer")
                f.write(chunk)
                h.update(chunk)
                received += len(chunk)
                progress("[RECV]", received, total_size, started)
                throttle_sleep(len(chunk), kbps, chaos)
                if chaos and random.random() < 0.03:
                    DialupFX.blip()

        actual_sha = h.hexdigest()
        print()
        if actual_sha == expected_sha:
            conn.sendall(b"OK\n")
            print(f"[RECV] Saved: {target}")
            print("[RECV] Checksum OK")
        else:
            conn.sendall(b"ERR checksum mismatch\n")
            print("[RECV] Checksum mismatch")
    except Exception as e:
        try:
            conn.sendall(f"ERR {e}\n".encode("utf-8", errors="replace"))
        except Exception:
            pass
        print(f"[RECV] Error: {e}")
    finally:
        conn.close()


def start_receiver(host: str, port: int, out_dir: Path, kbps: float, chaos: bool) -> None:
    local_ip = get_local_ip()
    print(f"Share this address with sender: {local_ip}:{port}")
    DialupFX.startup(host, port)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(5)
        print("[RECV] Waiting for connections... Ctrl+C to stop")
        while True:
            conn, addr = server.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr, out_dir, kbps, chaos),
                daemon=True,
            )
            thread.start()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retro dial-up style file transfer (Windows/Mac/Linux)"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    recv = sub.add_parser("receive", help="Start receiver server")
    recv.add_argument("--host", default="0.0.0.0", help="Bind host")
    recv.add_argument("--port", type=int, default=5050, help="Bind port")
    recv.add_argument(
        "--out-dir", default="received", help="Directory to save received files"
    )
    recv.add_argument(
        "--speed-kbps",
        type=float,
        default=42.0,
        help="Artificial max speed in kbps (dial-up feel)",
    )
    recv.add_argument(
        "--chaos",
        action="store_true",
        help="Add jitter, random pauses and beeps for extra nostalgia",
    )

    send = sub.add_parser("send", help="Send a file to receiver")
    send.add_argument("--host", required=True, help="Receiver IP/hostname")
    send.add_argument("--port", type=int, default=5050, help="Receiver port")
    send.add_argument("--file", required=True, help="File to send")
    send.add_argument(
        "--speed-kbps",
        type=float,
        default=42.0,
        help="Artificial max speed in kbps (dial-up feel)",
    )
    send.add_argument(
        "--chaos",
        action="store_true",
        help="Add jitter, random pauses and beeps for extra nostalgia",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.mode == "receive":
            start_receiver(
                host=args.host,
                port=args.port,
                out_dir=Path(args.out_dir),
                kbps=args.speed_kbps,
                chaos=args.chaos,
            )
        elif args.mode == "send":
            send_file(
                host=args.host,
                port=args.port,
                file_path=Path(args.file),
                kbps=args.speed_kbps,
                chaos=args.chaos,
            )
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        print("\nDisconnected.")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
