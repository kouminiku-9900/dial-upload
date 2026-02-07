#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

BUFFER_SIZE = 4096
PROTOCOL_VERSION = 1

ACOUSTIC_MAGIC = b"DUF1"
ACOUSTIC_SYNC = b"DIALUPSYNC"
ACOUSTIC_PREAMBLE_BITS = 192


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
    def startup(target: str) -> None:
        print("=" * 56)
        print(" Retro Dial-Up Transfer v0.2 ")
        print("=" * 56)
        print(f" Target: {target}")
        print("\n[MODEM] Handshake sequence")
        for stage in DialupFX.STAGES:
            time.sleep(random.uniform(0.12, 0.38))
            print(f"  {stage}")
        print("  *Static noise* krrrrk-chi-chi-bzzzt")
        print("  Link established. Ready for transfer.\n")

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
            delay += random.uniform(0.2, 0.9)
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


def unique_target(out_dir: Path, filename: str) -> Path:
    safe = os.path.basename(filename)
    target = out_dir / safe
    stem, suffix = target.stem, target.suffix
    idx = 1
    while target.exists():
        target = out_dir / f"{stem}_{idx}{suffix}"
        idx += 1
    return target


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
        sock.sendall(json.dumps(header).encode("utf-8") + b"\n")

        started = time.time()
        sent = 0
        with file_path.open("rb") as f:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)
                sent += len(chunk)
                progress("[SEND]", sent, file_size, started)
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

        filename = str(header["filename"])
        total_size = int(header["size"])
        expected_sha = str(header["sha256"])

        out_dir.mkdir(parents=True, exist_ok=True)
        target = unique_target(out_dir, filename)

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

        print()
        if h.hexdigest() == expected_sha:
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
    DialupFX.startup(f"LAN {host}:{port}")

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


def bytes_to_bits(data: bytes) -> list[int]:
    out: list[int] = []
    for b in data:
        for i in range(7, -1, -1):
            out.append((b >> i) & 1)
    return out


def bits_to_bytes(bits: list[int]) -> bytes:
    usable = (len(bits) // 8) * 8
    out = bytearray()
    for i in range(0, usable, 8):
        value = 0
        for bit in bits[i : i + 8]:
            value = (value << 1) | bit
        out.append(value)
    return bytes(out)


def build_acoustic_frame(file_path: Path) -> bytes:
    payload = file_path.read_bytes()
    header = {
        "version": PROTOCOL_VERSION,
        "filename": file_path.name,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return (
        ACOUSTIC_MAGIC
        + struct.pack(">IQ", len(header_bytes), len(payload))
        + header_bytes
        + payload
        + hashlib.sha256(payload).digest()
    )


def parse_acoustic_frame(frame: bytes) -> tuple[dict, bytes]:
    if len(frame) < 4 + 12 + 32:
        raise ValueError("frame too short")
    if frame[:4] != ACOUSTIC_MAGIC:
        raise ValueError("invalid frame magic")

    header_len, payload_len = struct.unpack(">IQ", frame[4:16])
    header_end = 16 + header_len
    payload_end = header_end + payload_len
    digest_end = payload_end + 32

    if digest_end > len(frame):
        raise ValueError("frame truncated")

    header = json.loads(frame[16:header_end].decode("utf-8"))
    payload = frame[header_end:payload_end]
    digest = frame[payload_end:digest_end]

    if hashlib.sha256(payload).digest() != digest:
        raise ValueError("payload checksum mismatch")
    if int(header.get("size", -1)) != len(payload):
        raise ValueError("size mismatch")

    return header, payload


def build_packet_bits(frame: bytes) -> list[int]:
    preamble = [i % 2 for i in range(ACOUSTIC_PREAMBLE_BITS)]
    sync_bits = bytes_to_bits(ACOUSTIC_SYNC)
    length_bits = bytes_to_bits(struct.pack(">I", len(frame)))
    return preamble + sync_bits + length_bits + bytes_to_bits(frame)


def synthesize_samples(bits: list[int], sample_rate: int, baud: int, f0: int, f1: int) -> list[int]:
    if baud <= 0:
        raise ValueError("baud must be > 0")
    n = int(sample_rate / baud)
    if n < 8:
        raise ValueError("sample_rate/baud too low")

    amp = 15000
    sym0 = [int(amp * math.sin(2.0 * math.pi * f0 * i / sample_rate)) for i in range(n)]
    sym1 = [int(amp * math.sin(2.0 * math.pi * f1 * i / sample_rate)) for i in range(n)]

    out: list[int] = []
    total = max(len(bits), 1)
    last_emit = 0.0
    for i, bit in enumerate(bits, start=1):
        out.extend(sym1 if bit else sym0)
        pct = (i / total) * 70.0
        if pct - last_emit >= 2.0 or i == total:
            print(f"[TXPROG] {pct:.1f}")
            last_emit = pct
    return out


def write_wav(samples: list[int], sample_rate: int, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def read_wav_mono16(in_path: Path) -> tuple[int, list[int]]:
    with wave.open(str(in_path), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())

    if width != 2:
        raise ValueError("only 16-bit PCM WAV is supported")

    values = list(struct.unpack("<" + "h" * (len(frames) // 2), frames))
    if channels == 1:
        return rate, values

    mono: list[int] = []
    for i in range(0, len(values), channels):
        mono.append(sum(values[i : i + channels]) // channels)
    return rate, mono


def goertzel_power(samples: list[int], freq: int, sample_rate: int) -> float:
    n = len(samples)
    k = int(0.5 + (n * freq) / sample_rate)
    omega = (2.0 * math.pi * k) / n
    coeff = 2.0 * math.cos(omega)
    q0 = 0.0
    q1 = 0.0
    q2 = 0.0
    for s in samples:
        q0 = coeff * q1 - q2 + s
        q2 = q1
        q1 = q0
    return q1 * q1 + q2 * q2 - q1 * q2 * coeff


def spectrum_bins(samples: list[int], sample_rate: int, bins: int = 24) -> list[int]:
    if not samples:
        return [0] * bins
    start_hz = 350
    end_hz = 3400
    freqs = [
        int(start_hz + (end_hz - start_hz) * i / max(bins - 1, 1))
        for i in range(bins)
    ]
    powers = [goertzel_power(samples, f, sample_rate) for f in freqs]
    peak = max(powers) if powers else 1.0
    if peak <= 0:
        return [0] * bins
    return [int(min(99.0, (p / peak) * 99.0)) for p in powers]


def faux_text_from_audio(samples: list[int]) -> str:
    if not samples:
        return ""
    charset = "01ABCDEF$%#@*+-=<>?"
    step = max(1, len(samples) // 12)
    out: list[str] = []
    for i in range(0, len(samples), step):
        seg = samples[i : i + step]
        if not seg:
            break
        avg = sum(abs(x) for x in seg) / len(seg)
        idx = int(avg / 800) % len(charset)
        out.append(charset[idx])
        if len(out) >= 24:
            break
    return "".join(out)


def demod_bits(samples: list[int], sample_rate: int, baud: int, f0: int, f1: int) -> tuple[list[int], int]:
    n = int(sample_rate / baud)
    if n < 8:
        raise ValueError("sample_rate/baud too low")

    sync_bits = bytes_to_bits(ACOUSTIC_SYNC)
    best: tuple[int, int] | None = None

    for offset in range(n):
        bits: list[int] = []
        idx = offset
        while idx + n <= len(samples):
            window = samples[idx : idx + n]
            p0 = goertzel_power(window, f0, sample_rate)
            p1 = goertzel_power(window, f1, sample_rate)
            bits.append(1 if p1 > p0 else 0)
            idx += n

        pos = find_bits(bits, sync_bits)
        if pos >= 0:
            score = len(bits) - pos
            if not best or score > best[1]:
                best = (offset, score)

    if best is None:
        raise ValueError("sync not found in audio")

    offset = best[0]
    bits: list[int] = []
    idx = offset
    while idx + n <= len(samples):
        window = samples[idx : idx + n]
        p0 = goertzel_power(window, f0, sample_rate)
        p1 = goertzel_power(window, f1, sample_rate)
        bits.append(1 if p1 > p0 else 0)
        idx += n
    return bits, n


def find_bits(haystack: list[int], needle: list[int]) -> int:
    if not needle or len(needle) > len(haystack):
        return -1
    end = len(haystack) - len(needle) + 1
    for i in range(end):
        if haystack[i : i + len(needle)] == needle:
            return i
    return -1


def decode_packet_from_samples(samples: list[int], sample_rate: int, baud: int, f0: int, f1: int) -> bytes:
    bits, _ = demod_bits(samples, sample_rate, baud, f0, f1)
    sync_bits = bytes_to_bits(ACOUSTIC_SYNC)
    pos = find_bits(bits, sync_bits)
    if pos < 0:
        raise ValueError("sync not found")

    start = pos + len(sync_bits)
    if start + 32 > len(bits):
        raise ValueError("missing frame length")

    length = struct.unpack(">I", bits_to_bytes(bits[start : start + 32]))[0]
    frame_start = start + 32
    frame_end = frame_start + (length * 8)
    if frame_end > len(bits):
        raise ValueError("recorded audio is too short for frame")

    frame_bytes = bits_to_bytes(bits[frame_start:frame_end])
    if len(frame_bytes) != length:
        raise ValueError("frame size decode mismatch")
    return frame_bytes


def play_wav(path: Path, sample_rate: int, samples: list[int]) -> None:
    try:
        import array
        import sounddevice as sd  # type: ignore

        arr = array.array("f", (s / 32768.0 for s in samples))
        sd.play(arr, samplerate=sample_rate, blocking=True)
        return
    except Exception:
        pass

    if sys.platform == "darwin" and shutil.which("afplay"):
        subprocess.run(["afplay", str(path)], check=True)
        return

    if sys.platform.startswith("win"):
        cmd = (
            "Add-Type -AssemblyName presentationCore;"
            f"(New-Object Media.SoundPlayer '{str(path).replace("'", "''")}').PlaySync();"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True)
        return

    for candidate in ("aplay", "paplay"):
        if shutil.which(candidate):
            subprocess.run([candidate, str(path)], check=True)
            return

    raise RuntimeError("No audio playback backend found. Install sounddevice or use --no-play.")


def record_from_mic(seconds: float, sample_rate: int) -> list[int]:
    try:
        import sounddevice as sd  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Mic capture needs python package 'sounddevice'. Install with: pip install sounddevice"
        ) from e

    out: list[int] = []
    started = time.time()
    last_emit = 0.0
    blocksize = int(sample_rate * 0.18)
    if blocksize < 64:
        blocksize = 64

    def callback(indata, frames, _time_info, status) -> None:  # type: ignore[no-untyped-def]
        nonlocal out, last_emit
        if status:
            print(f"[ACOUSTIC RECV] audio status: {status}")
        for i in range(frames):
            val = int(max(-1.0, min(1.0, float(indata[i][0]))) * 32767)
            out.append(val)

        elapsed = time.time() - started
        ratio = min(1.0, elapsed / max(seconds, 1e-6))
        now = time.time()
        if now - last_emit >= 0.25:
            last_emit = now
            print(f"[RXPROG] {ratio * 100.0:.1f}")
            bins = spectrum_bins(out[-blocksize:], sample_rate, bins=28)
            print("[SPAN] " + ",".join(str(v) for v in bins))
            faux = faux_text_from_audio(out[-blocksize:])
            if faux:
                print(f"[ASCII] {faux}")

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        callback=callback,
    ):
        end_at = time.time() + seconds
        while time.time() < end_at:
            time.sleep(0.05)
    print("[RXPROG] 100.0")
    return out


def acoustic_send(
    file_path: Path,
    wav_out: Path,
    play: bool,
    sample_rate: int,
    baud: int,
    f0: int,
    f1: int,
) -> None:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"file not found: {file_path}")

    frame = build_acoustic_frame(file_path)
    bits = build_packet_bits(frame)
    print("[TXPROG] 0.0")
    samples = synthesize_samples(bits, sample_rate, baud, f0, f1)
    print("[TXPROG] 80.0")
    write_wav(samples, sample_rate, wav_out)
    print("[TXPROG] 90.0")

    duration = len(samples) / sample_rate
    print(f"[ACOUSTIC SEND] WAV written: {wav_out}")
    print(f"[ACOUSTIC SEND] Estimated transfer time: {duration:.1f} seconds")

    if play:
        DialupFX.startup("ACOUSTIC speaker")
        print("[ACOUSTIC SEND] Playing from speaker now...")
        play_wav(wav_out, sample_rate, samples)
        print("[ACOUSTIC SEND] Playback finished.")
    print("[TXPROG] 100.0")


def acoustic_receive(
    out_dir: Path,
    sample_rate: int,
    baud: int,
    f0: int,
    f1: int,
    wav_in: Path | None,
    record_seconds: float,
    save_recorded_wav: Path | None,
) -> None:
    print("[LAMP] RED")
    print("[RXPROG] 0.0")
    if wav_in:
        read_rate, samples = read_wav_mono16(wav_in)
        if read_rate != sample_rate:
            raise ValueError(f"wav sample rate mismatch: expected {sample_rate}, got {read_rate}")
        print(f"[ACOUSTIC RECV] Decoding WAV: {wav_in}")
        print("[RXPROG] 50.0")
        bins = spectrum_bins(samples[: int(sample_rate * 0.2)], sample_rate, bins=28)
        print("[SPAN] " + ",".join(str(v) for v in bins))
    else:
        DialupFX.startup("ACOUSTIC microphone")
        print("[LAMP] YELLOW")
        print(f"[ACOUSTIC RECV] Recording from mic for {record_seconds:.1f}s ...")
        samples = record_from_mic(record_seconds, sample_rate)
        print("[ACOUSTIC RECV] Recording complete.")
        if save_recorded_wav:
            write_wav(samples, sample_rate, save_recorded_wav)
            print(f"[ACOUSTIC RECV] Raw recording saved: {save_recorded_wav}")

    print("[ACOUSTIC RECV] Demodulating...")
    frame = decode_packet_from_samples(samples, sample_rate, baud, f0, f1)
    print("[RXPROG] 92.0")
    header, payload = parse_acoustic_frame(frame)
    preview = payload[:240].decode("utf-8", errors="ignore").replace("\n", " ")
    if preview:
        print(f"[ASCII] {preview[:120]}")

    out_dir.mkdir(parents=True, exist_ok=True)
    target = unique_target(out_dir, str(header.get("filename", "received.bin")))
    target.write_bytes(payload)

    expected = str(header.get("sha256", ""))
    actual = hashlib.sha256(payload).hexdigest()
    if expected and expected != actual:
        print("[LAMP] RED")
        raise ValueError("decoded checksum mismatch")

    print(f"[ACOUSTIC RECV] Saved: {target}")
    print("[ACOUSTIC RECV] Checksum OK")
    print("[RXPROG] 100.0")
    print("[LAMP] GREEN")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retro dial-up style file transfer (LAN and speaker/mic acoustic)"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    recv = sub.add_parser("receive", help="Start LAN receiver server")
    recv.add_argument("--host", default="0.0.0.0", help="Bind host")
    recv.add_argument("--port", type=int, default=5050, help="Bind port")
    recv.add_argument("--out-dir", default="received", help="Save directory")
    recv.add_argument("--speed-kbps", type=float, default=42.0, help="Artificial speed limit")
    recv.add_argument("--chaos", action="store_true", help="Add jitter and beeps")

    send = sub.add_parser("send", help="Send a file over LAN")
    send.add_argument("--host", required=True, help="Receiver IP/hostname")
    send.add_argument("--port", type=int, default=5050, help="Receiver port")
    send.add_argument("--file", required=True, help="File to send")
    send.add_argument("--speed-kbps", type=float, default=42.0, help="Artificial speed limit")
    send.add_argument("--chaos", action="store_true", help="Add jitter and beeps")

    asend = sub.add_parser("acoustic-send", help="Encode and play transfer audio from speaker")
    asend.add_argument("--file", required=True, help="File to send")
    asend.add_argument("--wav-out", default="dialup_tx.wav", help="Output WAV path")
    asend.add_argument("--no-play", action="store_true", help="Only generate WAV, do not play")
    asend.add_argument("--sample-rate", type=int, default=44100)
    asend.add_argument("--baud", type=int, default=80)
    asend.add_argument("--f0", type=int, default=1200, help="Frequency for bit 0")
    asend.add_argument("--f1", type=int, default=2200, help="Frequency for bit 1")

    arecv = sub.add_parser("acoustic-receive", help="Record from mic and decode transfer audio")
    arecv.add_argument("--out-dir", default="received", help="Save directory")
    arecv.add_argument("--sample-rate", type=int, default=44100)
    arecv.add_argument("--baud", type=int, default=80)
    arecv.add_argument("--f0", type=int, default=1200)
    arecv.add_argument("--f1", type=int, default=2200)
    arecv.add_argument("--record-seconds", type=float, default=30.0)
    arecv.add_argument("--wav-in", help="Decode from existing WAV instead of mic capture")
    arecv.add_argument("--save-recorded-wav", help="Save raw mic capture WAV")

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
        elif args.mode == "acoustic-send":
            acoustic_send(
                file_path=Path(args.file),
                wav_out=Path(args.wav_out),
                play=not args.no_play,
                sample_rate=args.sample_rate,
                baud=args.baud,
                f0=args.f0,
                f1=args.f1,
            )
        elif args.mode == "acoustic-receive":
            acoustic_receive(
                out_dir=Path(args.out_dir),
                sample_rate=args.sample_rate,
                baud=args.baud,
                f0=args.f0,
                f1=args.f1,
                wav_in=Path(args.wav_in) if args.wav_in else None,
                record_seconds=args.record_seconds,
                save_recorded_wav=Path(args.save_recorded_wav) if args.save_recorded_wav else None,
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
