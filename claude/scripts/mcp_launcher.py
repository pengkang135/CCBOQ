"""MCP launcher — spawns npx/uvx without cmd windows on Windows."""
import subprocess
import sys
import os

# Drop the script path and optional wrapper tag
args = sys.argv[1:]

if os.name == 'nt':
    flags = subprocess.CREATE_NO_WINDOW
    # Hide the console window; pythonw.exe already has none,
    # but this ensures child processes also get no window.
    startup = subprocess.STARTUPINFO()
    startup.wShowWindow = subprocess.SW_HIDE
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
else:
    flags = 0
    startup = None

sys.exit(subprocess.run(args, creationflags=flags, startupinfo=startup).returncode)
