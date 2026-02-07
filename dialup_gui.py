#!/usr/bin/env python3
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class DialupGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Retro Dial-Up Transfer")
        self.geometry("920x680")
        self.minsize(800, 560)

        self.base_dir = Path(__file__).resolve().parent
        self.cli_path = self.base_dir / "dialup_transfer.py"

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.receiver_proc: subprocess.Popen[str] | None = None
        self.sender_proc: subprocess.Popen[str] | None = None
        self.last_ascii = ""

        self._build_ui()
        self.after(120, self._drain_logs)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="Retro Dial-Up Transfer", font=("Courier", 20, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(root, text="LAN mode + Speaker/Mic acoustic mode").pack(anchor="w", pady=(0, 12))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="x")

        recv_tab = ttk.Frame(notebook, padding=10)
        send_tab = ttk.Frame(notebook, padding=10)
        notebook.add(recv_tab, text="Receive")
        notebook.add(send_tab, text="Send")

        self._build_receive_tab(recv_tab)
        self._build_send_tab(send_tab)

        log_wrap = ttk.LabelFrame(root, text="Connection Log", padding=8)
        log_wrap.pack(fill="both", expand=True, pady=(12, 0))

        self.log_text = tk.Text(log_wrap, height=18, wrap="word", font=("Courier", 11))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

    def _build_receive_tab(self, parent: ttk.Frame) -> None:
        self.recv_transport = tk.StringVar(value="lan")
        self.recv_host = tk.StringVar(value="0.0.0.0")
        self.recv_port = tk.StringVar(value="5050")
        self.recv_speed = tk.StringVar(value="42")
        self.recv_outdir = tk.StringVar(value="received")
        self.recv_chaos = tk.BooleanVar(value=True)
        self.recv_record_seconds = tk.StringVar(value="30")
        self.recv_passphrase = tk.StringVar(value="")
        self.recv_allow_unauth = tk.BooleanVar(value=False)

        self._row(parent, 0, "Transport", self.recv_transport, is_combo=True, options=["lan", "acoustic"])
        self._row(parent, 1, "Bind Host", self.recv_host)
        self._row(parent, 2, "Port", self.recv_port)
        self._row(parent, 3, "Speed (kbps)", self.recv_speed)
        self._row(parent, 4, "Output Dir", self.recv_outdir)
        self._row(parent, 5, "Record Seconds", self.recv_record_seconds)
        ttk.Label(parent, text="Acoustic Passphrase").grid(row=6, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(parent, textvariable=self.recv_passphrase, show="*").grid(row=6, column=1, sticky="ew", pady=4)

        ttk.Checkbutton(parent, text="Chaos mode (LAN only)", variable=self.recv_chaos).grid(
            row=7, column=1, sticky="w", pady=(4, 2)
        )
        ttk.Checkbutton(parent, text="Allow unauthenticated acoustic frames (unsafe)", variable=self.recv_allow_unauth).grid(
            row=8, column=1, sticky="w", pady=(0, 8)
        )

        btns = ttk.Frame(parent)
        btns.grid(row=9, column=1, sticky="w")
        self.start_recv_btn = ttk.Button(btns, text="Start Receiver", command=self.start_receiver)
        self.start_recv_btn.pack(side="left", padx=(0, 8))
        self.stop_recv_btn = ttk.Button(btns, text="Stop Receiver", command=self.stop_receiver, state="disabled")
        self.stop_recv_btn.pack(side="left")

        status = ttk.Frame(parent)
        status.grid(row=10, column=1, sticky="ew", pady=(10, 2))
        status.columnconfigure(1, weight=1)
        ttk.Label(status, text="Receive Progress").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.recv_progress = ttk.Progressbar(status, mode="determinate", maximum=100)
        self.recv_progress.grid(row=0, column=1, sticky="ew")

        lamp_row = ttk.Frame(parent)
        lamp_row.grid(row=11, column=1, sticky="w", pady=(8, 4))
        ttk.Label(lamp_row, text="Receive Lamp").pack(side="left", padx=(0, 8))
        self.lamp_canvas = tk.Canvas(lamp_row, width=20, height=20, highlightthickness=0)
        self.lamp_canvas.pack(side="left")
        self.lamp_led = self.lamp_canvas.create_oval(2, 2, 18, 18, fill="#9a1f1f", outline="#451010")

        preview_wrap = ttk.LabelFrame(parent, text="Live Data Text", padding=6)
        preview_wrap.grid(row=12, column=1, sticky="ew", pady=(4, 4))
        self.preview_text = tk.Text(preview_wrap, height=4, wrap="word", font=("Courier", 10))
        self.preview_text.pack(fill="x", expand=True)
        self.preview_text.configure(state="disabled")

        span_wrap = ttk.LabelFrame(parent, text="Live Spana", padding=6)
        span_wrap.grid(row=13, column=1, sticky="ew", pady=(4, 2))
        self.span_canvas = tk.Canvas(span_wrap, width=560, height=110, bg="#0c0f10", highlightthickness=0)
        self.span_canvas.pack(fill="x", expand=True)
        self._draw_spectrum([0] * 28)

    def _build_send_tab(self, parent: ttk.Frame) -> None:
        self.send_transport = tk.StringVar(value="lan")
        self.send_host = tk.StringVar(value="127.0.0.1")
        self.send_port = tk.StringVar(value="5050")
        self.send_speed = tk.StringVar(value="42")
        self.send_file = tk.StringVar(value="")
        self.send_chaos = tk.BooleanVar(value=True)
        self.send_play_audio = tk.BooleanVar(value=True)
        self.send_passphrase = tk.StringVar(value="")
        self.send_allow_unauth = tk.BooleanVar(value=False)

        self._row(parent, 0, "Transport", self.send_transport, is_combo=True, options=["lan", "acoustic"])
        self._row(parent, 1, "Receiver Host", self.send_host)
        self._row(parent, 2, "Port", self.send_port)
        self._row(parent, 3, "Speed (kbps)", self.send_speed)

        ttk.Label(parent, text="File").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=4)
        file_row = ttk.Frame(parent)
        file_row.grid(row=4, column=1, sticky="ew", pady=4)
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.send_file).grid(row=0, column=0, sticky="ew")
        ttk.Button(file_row, text="Browse", command=self.browse_file).grid(row=0, column=1, padx=(8, 0))

        ttk.Checkbutton(parent, text="Chaos mode (LAN only)", variable=self.send_chaos).grid(
            row=5, column=1, sticky="w", pady=(4, 4)
        )
        ttk.Checkbutton(parent, text="Play through speaker (Acoustic only)", variable=self.send_play_audio).grid(
            row=6, column=1, sticky="w", pady=(0, 8)
        )
        ttk.Label(parent, text="Acoustic Passphrase").grid(row=7, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(parent, textvariable=self.send_passphrase, show="*").grid(row=7, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(parent, text="Allow unauthenticated acoustic send (unsafe)", variable=self.send_allow_unauth).grid(
            row=8, column=1, sticky="w", pady=(0, 8)
        )

        self.send_btn = ttk.Button(parent, text="Send File", command=self.send_once)
        self.send_btn.grid(row=9, column=1, sticky="w")

        progress_row = ttk.Frame(parent)
        progress_row.grid(row=10, column=1, sticky="ew", pady=(8, 2))
        progress_row.columnconfigure(1, weight=1)
        ttk.Label(progress_row, text="Send Progress").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.send_progress = ttk.Progressbar(progress_row, mode="determinate", maximum=100)
        self.send_progress.grid(row=0, column=1, sticky="ew")

        parent.columnconfigure(1, weight=1)

    @staticmethod
    def _row(
        parent: ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        is_combo: bool = False,
        options: list[str] | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        if is_combo:
            combo = ttk.Combobox(parent, textvariable=var, values=options or [], state="readonly")
            combo.grid(row=row, column=1, sticky="ew", pady=4)
        else:
            ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)

    def browse_file(self) -> None:
        path = filedialog.askopenfilename()
        if path:
            self.send_file.set(path)

    def start_receiver(self) -> None:
        if self.receiver_proc and self.receiver_proc.poll() is None:
            return

        transport = self.recv_transport.get().strip().lower()
        extra_env: dict[str, str] | None = None
        self.recv_progress.configure(value=0)
        self._set_lamp("red")
        self._append_preview("")
        self._draw_spectrum([0] * 28)
        if transport == "acoustic":
            passphrase = self.recv_passphrase.get().strip()
            allow_unauth = self.recv_allow_unauth.get()
            if not passphrase and not allow_unauth:
                messagebox.showerror(
                    "Passphrase required",
                    "Acoustic receive requires passphrase unless unauthenticated mode is explicitly enabled.",
                )
                return
            cmd = [
                sys.executable,
                str(self.cli_path),
                "acoustic-receive",
                "--out-dir",
                self.recv_outdir.get().strip(),
                "--record-seconds",
                self.recv_record_seconds.get().strip(),
            ]
            if passphrase:
                cmd.extend(["--passphrase-env", "DIALUP_PASSPHRASE"])
                extra_env = {"DIALUP_PASSPHRASE": passphrase}
            if allow_unauth:
                cmd.append("--allow-unauthenticated")
        else:
            cmd = [
                sys.executable,
                str(self.cli_path),
                "receive",
                "--host",
                self.recv_host.get().strip(),
                "--port",
                self.recv_port.get().strip(),
                "--out-dir",
                self.recv_outdir.get().strip(),
                "--speed-kbps",
                self.recv_speed.get().strip(),
            ]
            if self.recv_chaos.get():
                cmd.append("--chaos")

        try:
            self.receiver_proc = self._spawn(cmd, "[RECV]", extra_env=extra_env)
            self.start_recv_btn.configure(state="disabled")
            self.stop_recv_btn.configure(state="normal")
            threading.Thread(target=self._wait_receiver, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Start failed", str(e))

    def _wait_receiver(self) -> None:
        if not self.receiver_proc:
            return
        code = self.receiver_proc.wait()
        self.log_queue.put(f"[RECV] Process exited with code {code}\n")
        self.receiver_proc = None
        self.after(0, self._receiver_buttons_reset)

    def _receiver_buttons_reset(self) -> None:
        self.start_recv_btn.configure(state="normal")
        self.stop_recv_btn.configure(state="disabled")

    def stop_receiver(self) -> None:
        if not self.receiver_proc:
            return
        self._terminate(self.receiver_proc, "[RECV]")
        self.receiver_proc = None
        self._receiver_buttons_reset()

    def send_once(self) -> None:
        if self.sender_proc and self.sender_proc.poll() is None:
            messagebox.showinfo("Busy", "A send task is already running.")
            return

        file_path = Path(self.send_file.get().strip())
        if not file_path.exists() or not file_path.is_file():
            messagebox.showerror("Invalid file", "Select a valid file to send.")
            return

        transport = self.send_transport.get().strip().lower()
        extra_env: dict[str, str] | None = None
        self.send_progress.configure(value=0)
        if transport == "acoustic":
            passphrase = self.send_passphrase.get().strip()
            allow_unauth = self.send_allow_unauth.get()
            if not passphrase and not allow_unauth:
                messagebox.showerror(
                    "Passphrase required",
                    "Acoustic send requires passphrase unless unauthenticated mode is explicitly enabled.",
                )
                return
            cmd = [
                sys.executable,
                str(self.cli_path),
                "acoustic-send",
                "--file",
                str(file_path),
            ]
            if not self.send_play_audio.get():
                cmd.append("--no-play")
            if passphrase:
                cmd.extend(["--passphrase-env", "DIALUP_PASSPHRASE"])
                extra_env = {"DIALUP_PASSPHRASE": passphrase}
            if allow_unauth:
                cmd.append("--allow-unauthenticated")
        else:
            cmd = [
                sys.executable,
                str(self.cli_path),
                "send",
                "--host",
                self.send_host.get().strip(),
                "--port",
                self.send_port.get().strip(),
                "--file",
                str(file_path),
                "--speed-kbps",
                self.send_speed.get().strip(),
            ]
            if self.send_chaos.get():
                cmd.append("--chaos")

        try:
            self.sender_proc = self._spawn(cmd, "[SEND]", extra_env=extra_env)
            self.send_btn.configure(state="disabled")
            threading.Thread(target=self._wait_sender, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Send failed", str(e))

    def _wait_sender(self) -> None:
        if not self.sender_proc:
            return
        code = self.sender_proc.wait()
        self.log_queue.put(f"[SEND] Process exited with code {code}\n")
        if code != 0:
            self.log_queue.put("[SEND] [TXPROG] 0.0\n")
        self.sender_proc = None
        self.after(0, lambda: self.send_btn.configure(state="normal"))

    @staticmethod
    def _format_cmd_for_log(cmd: list[str]) -> str:
        out: list[str] = []
        skip_next = False
        for i, part in enumerate(cmd):
            if skip_next:
                out.append("***")
                skip_next = False
                continue
            out.append(part)
            if part == "--passphrase" and i + 1 < len(cmd):
                skip_next = True
        return " ".join(out)

    def _spawn(self, cmd: list[str], tag: str, extra_env: dict[str, str] | None = None) -> subprocess.Popen[str]:
        self.log_queue.put(f"{tag} $ {self._format_cmd_for_log(cmd)}\n")
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        proc = subprocess.Popen(
            cmd,
            cwd=self.base_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._pump_output, args=(proc, tag), daemon=True).start()
        return proc

    def _pump_output(self, proc: subprocess.Popen[str], tag: str) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self.log_queue.put(f"{tag} {line}")

    def _set_lamp(self, color: str) -> None:
        mapping = {
            "red": ("#a11f1f", "#451010"),
            "yellow": ("#bfa31c", "#595018"),
            "green": ("#18a150", "#0d4a23"),
        }
        fill, outline = mapping.get(color, mapping["red"])
        self.lamp_canvas.itemconfig(self.lamp_led, fill=fill, outline=outline)

    @staticmethod
    def _sanitize_ascii(text: str, limit: int = 120) -> str:
        out = []
        for ch in text:
            if ch in ("\n", "\r", "\t"):
                out.append(" ")
            elif 32 <= ord(ch) <= 126:
                out.append(ch)
            else:
                out.append(".")
        return "".join(out).strip()[:limit]

    @staticmethod
    def _extract_event_payload(line: str, tag: str) -> str | None:
        pattern = rf"^(?:\[(?:SEND|RECV)\]\s+)?\[{re.escape(tag)}\]\s*(.*)$"
        m = re.match(pattern, line.strip())
        if not m:
            return None
        return m.group(1).strip()

    def _append_preview(self, text: str) -> None:
        safe_text = self._sanitize_ascii(text)
        if not safe_text:
            self.preview_text.configure(state="normal")
            self.preview_text.delete("1.0", "end")
            self.preview_text.configure(state="disabled")
            self.last_ascii = ""
            return
        if safe_text == self.last_ascii:
            return
        self.last_ascii = safe_text
        self.preview_text.configure(state="normal")
        self.preview_text.insert("end", safe_text + "\n")
        self.preview_text.see("end")
        if float(self.preview_text.index("end-1c").split(".")[0]) > 8:
            self.preview_text.delete("1.0", "2.0")
        self.preview_text.configure(state="disabled")

    def _draw_spectrum(self, bins: list[int]) -> None:
        self.span_canvas.delete("all")
        w = int(self.span_canvas.winfo_width() or 560)
        h = int(self.span_canvas.winfo_height() or 110)
        n = max(1, len(bins))
        bw = max(2, w // n)
        for i, v in enumerate(bins):
            x0 = i * bw + 1
            x1 = x0 + bw - 2
            height = int((max(0, min(99, v)) / 99.0) * (h - 14))
            y0 = h - 6 - height
            y1 = h - 6
            color = "#3db8ff" if v < 70 else "#8ef77f"
            self.span_canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
        self.span_canvas.create_line(0, h - 6, w, h - 6, fill="#3f4b52")

    def _handle_event_line(self, line: str) -> None:
        tx_payload = self._extract_event_payload(line, "TXPROG")
        if tx_payload is not None:
            try:
                val = float(tx_payload)
                self.send_progress.configure(value=max(0.0, min(100.0, val)))
            except ValueError:
                pass
        rx_payload = self._extract_event_payload(line, "RXPROG")
        if rx_payload is not None:
            try:
                val = float(rx_payload)
                self.recv_progress.configure(value=max(0.0, min(100.0, val)))
            except ValueError:
                pass
        lamp_payload = self._extract_event_payload(line, "LAMP")
        if lamp_payload is not None:
            val = lamp_payload.lower()
            if "green" in val:
                self._set_lamp("green")
            elif "yellow" in val:
                self._set_lamp("yellow")
            else:
                self._set_lamp("red")
        ascii_payload = self._extract_event_payload(line, "ASCII")
        if ascii_payload is not None:
            text = self._sanitize_ascii(ascii_payload)
            if text:
                self._append_preview(text)
        span_payload = self._extract_event_payload(line, "SPAN")
        if span_payload is not None:
            try:
                bins = [int(x) for x in span_payload.split(",") if x.strip()][:64]
                if bins:
                    self._draw_spectrum(bins)
            except ValueError:
                pass

    def _terminate(self, proc: subprocess.Popen[str], tag: str) -> None:
        if proc.poll() is not None:
            return
        self.log_queue.put(f"{tag} Stopping process...\n")
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)
        self.log_queue.put(f"{tag} Stopped.\n")

    def _drain_logs(self) -> None:
        wrote = False
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event_line(line)
            wrote = True
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        if wrote:
            self.update_idletasks()
        self.after(120, self._drain_logs)

    def on_close(self) -> None:
        try:
            if self.sender_proc and self.sender_proc.poll() is None:
                self._terminate(self.sender_proc, "[SEND]")
            if self.receiver_proc and self.receiver_proc.poll() is None:
                self._terminate(self.receiver_proc, "[RECV]")
        finally:
            self.destroy()


def main() -> int:
    app = DialupGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
