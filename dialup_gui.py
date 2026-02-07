#!/usr/bin/env python3
import queue
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

        self._row(parent, 0, "Transport", self.recv_transport, is_combo=True, options=["lan", "acoustic"])
        self._row(parent, 1, "Bind Host", self.recv_host)
        self._row(parent, 2, "Port", self.recv_port)
        self._row(parent, 3, "Speed (kbps)", self.recv_speed)
        self._row(parent, 4, "Output Dir", self.recv_outdir)
        self._row(parent, 5, "Record Seconds", self.recv_record_seconds)

        ttk.Checkbutton(parent, text="Chaos mode (LAN only)", variable=self.recv_chaos).grid(
            row=6, column=1, sticky="w", pady=(4, 8)
        )

        btns = ttk.Frame(parent)
        btns.grid(row=7, column=1, sticky="w")
        self.start_recv_btn = ttk.Button(btns, text="Start Receiver", command=self.start_receiver)
        self.start_recv_btn.pack(side="left", padx=(0, 8))
        self.stop_recv_btn = ttk.Button(btns, text="Stop Receiver", command=self.stop_receiver, state="disabled")
        self.stop_recv_btn.pack(side="left")

    def _build_send_tab(self, parent: ttk.Frame) -> None:
        self.send_transport = tk.StringVar(value="lan")
        self.send_host = tk.StringVar(value="127.0.0.1")
        self.send_port = tk.StringVar(value="5050")
        self.send_speed = tk.StringVar(value="42")
        self.send_file = tk.StringVar(value="")
        self.send_chaos = tk.BooleanVar(value=True)
        self.send_play_audio = tk.BooleanVar(value=True)

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

        self.send_btn = ttk.Button(parent, text="Send File", command=self.send_once)
        self.send_btn.grid(row=7, column=1, sticky="w")

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
        if transport == "acoustic":
            cmd = [
                sys.executable,
                str(self.cli_path),
                "acoustic-receive",
                "--out-dir",
                self.recv_outdir.get().strip(),
                "--record-seconds",
                self.recv_record_seconds.get().strip(),
            ]
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
            self.receiver_proc = self._spawn(cmd, "[RECV]")
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
        if transport == "acoustic":
            cmd = [
                sys.executable,
                str(self.cli_path),
                "acoustic-send",
                "--file",
                str(file_path),
            ]
            if not self.send_play_audio.get():
                cmd.append("--no-play")
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
            self.sender_proc = self._spawn(cmd, "[SEND]")
            self.send_btn.configure(state="disabled")
            threading.Thread(target=self._wait_sender, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Send failed", str(e))

    def _wait_sender(self) -> None:
        if not self.sender_proc:
            return
        code = self.sender_proc.wait()
        self.log_queue.put(f"[SEND] Process exited with code {code}\n")
        self.sender_proc = None
        self.after(0, lambda: self.send_btn.configure(state="normal"))

    def _spawn(self, cmd: list[str], tag: str) -> subprocess.Popen[str]:
        self.log_queue.put(f"{tag} $ {' '.join(cmd)}\n")
        proc = subprocess.Popen(
            cmd,
            cwd=self.base_dir,
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
