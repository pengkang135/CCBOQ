"""MCP launcher — spawns npx/uvx without cmd windows on Windows."""
import subprocess
import sys
import os
import shutil

args = sys.argv[1:]

if os.name == 'nt':
    flags = subprocess.CREATE_NO_WINDOW
    startup = subprocess.STARTUPINFO()
    startup.wShowWindow = subprocess.SW_HIDE
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    # Resolve npx/uvx to direct exe calls to avoid cmd.exe (and conhost pollution)
    if args and args[0] == 'npx':
        node_exe = r'D:\Program Files\nodejs\node.exe'
        npx_script = r'D:\Program Files\nodejs\node_modules\npm\bin\npx-cli.js'
        args = [node_exe, npx_script] + args[1:]
        shell = False
    elif args and args[0] == 'uvx':
        uvx_exe = shutil.which('uvx') or r'C:\Users\Kevin\.local\bin\uvx.exe'
        args = [uvx_exe] + args[1:]
        shell = False
    else:
        shell = True

    sys.exit(subprocess.run(args, creationflags=flags, startupinfo=startup, shell=shell,
                             stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr).returncode)
else:
    sys.exit(subprocess.run(args, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr).returncode)
