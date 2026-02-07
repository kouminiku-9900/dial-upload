@echo off
cd /d "%~dp0"
python -c "import subprocess, sys; subprocess.Popen([sys.executable.replace('python.exe', 'pythonw.exe'), 'dialup_gui.py'])"
