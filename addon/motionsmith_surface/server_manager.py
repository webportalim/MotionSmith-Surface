"""MotionSmith Surface - ComfyUI Server Manager.

Handles starting, stopping, and monitoring the lifecycle of the local minimal ComfyUI server.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

_SERVER_PROCESS = None
_SERVER_START_TIME = 0.0
_SERVER_STATE = "OFFLINE"  # "OFFLINE" | "STARTING" | "ONLINE" | "STOPPING"


def is_port_in_use(port: int = 8188, host: str = "127.0.0.1") -> bool:
    """Check if the given port is actively listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def is_server_alive(server_url: str = "http://127.0.0.1:8188", timeout: float = 0.8) -> bool:
    """Query ComfyUI /system_stats endpoint to check if the server is responsive."""
    try:
        parts = server_url.replace("http://", "").replace("https://", "").split(":")
        host = parts[0]
        port = int(parts[1].split("/")[0]) if len(parts) > 1 else 8188
        if not is_port_in_use(port, host):
            return False
    except Exception:
        return False

    url = f"{server_url.rstrip('/')}/system_stats"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MotionSmithSurface/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return "system" in data
    except Exception:
        pass
    return False


def get_pids_on_port(port: int = 8188) -> list[int]:
    """Find all process IDs currently holding the port on Windows."""
    pids = set()
    if sys.platform != "win32":
        return list(pids)

    # 1. Try netstat (filtering specifically for LISTENING sockets)
    try:
        out = subprocess.check_output(
            "netstat -ano",
            shell=True,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP":
                local_addr = parts[1]
                state = parts[3]
                if local_addr.endswith(f":{port}"):
                    try:
                        pid = int(parts[4])
                        if pid > 0:
                            pids.add(pid)
                    except ValueError:
                        pass
    except Exception:
        pass

    # 2. Try powershell Get-NetTCPConnection as fallback
    if not pids:
        try:
            ps_cmd = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
            out = subprocess.check_output(["powershell", "-Command", ps_cmd], text=True, stderr=subprocess.DEVNULL)
            for line in out.strip().splitlines():
                try:
                    pid = int(line.strip())
                    if pid > 0:
                        pids.add(pid)
                except ValueError:
                    pass
        except Exception:
            pass

    return list(pids)


def get_server_state(port: int = 8188, url: str | None = None) -> str:
    """Return the current lifecycle state: OFFLINE, STARTING, ONLINE, or STOPPING."""
    global _SERVER_STATE, _SERVER_START_TIME, _SERVER_PROCESS

    target_url = url.rstrip("/") if url else f"http://127.0.0.1:{port}"
    alive = is_server_alive(target_url, timeout=0.3)
    if alive:
        _SERVER_STATE = "ONLINE"
        _SERVER_START_TIME = 0.0
        return "ONLINE"

    if _SERVER_STATE == "STARTING":
        # Check if process unexpectedly crashed
        if _SERVER_PROCESS is not None and _SERVER_PROCESS.poll() is not None:
            _SERVER_STATE = "OFFLINE"
            _SERVER_START_TIME = 0.0
            return "OFFLINE"

        # Check if startup timed out (> 35 seconds)
        if _SERVER_START_TIME > 0 and (time.time() - _SERVER_START_TIME > 35.0):
            _SERVER_STATE = "OFFLINE"
            _SERVER_START_TIME = 0.0
            return "OFFLINE"

        return "STARTING"

    if _SERVER_STATE == "STOPPING":
        return "STOPPING"

    _SERVER_STATE = "OFFLINE"
    return "OFFLINE"


def start_server(
    comfyui_dir: str,
    python_exe: str,
    port: int = 8188,
    show_console: bool = True,
) -> tuple[bool, str]:
    """Start ComfyUI server.
    
    If show_console is True on Windows, opens a dedicated console window so the user
    can watch server startup and generation progress in real time.
    """
    global _SERVER_PROCESS, _SERVER_START_TIME, _SERVER_STATE

    if is_server_alive(f"http://127.0.0.1:{port}"):
        _SERVER_STATE = "ONLINE"
        return True, f"Server is already running on port {port}."

    if is_port_in_use(port):
        return False, f"Port {port} is occupied by another service. Stop it or choose another port."

    if not os.path.isdir(comfyui_dir):
        _SERVER_STATE = "OFFLINE"
        return False, f"ComfyUI directory not found: {comfyui_dir}. (If already running, press Refresh)"

    main_py = os.path.join(comfyui_dir, "main.py")
    if not os.path.isfile(main_py):
        _SERVER_STATE = "OFFLINE"
        return False, f"main.py not found in ComfyUI directory: {main_py}"

    if not os.path.isfile(python_exe):
        _SERVER_STATE = "OFFLINE"
        return False, f"Python executable not found: {python_exe}"

    cmd = [
        python_exe,
        "main.py",
        "--listen", "127.0.0.1",
        "--port", str(port),
        "--preview-method", "auto",
    ]

    env = os.environ.copy()
    env["U2NET_HOME"] = os.path.join(comfyui_dir, "models", "rembg")
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    env["PYTHONUTF8"] = "1"

    _SERVER_STATE = "STARTING"
    _SERVER_START_TIME = time.time()

    try:
        if sys.platform == "win32" and show_console:
            # Launch in an interactive console window
            creationflags = subprocess.CREATE_NEW_CONSOLE
            proc = subprocess.Popen(
                cmd,
                cwd=comfyui_dir,
                env=env,
                creationflags=creationflags,
            )
        else:
            # Launch in background with output redirected to log file
            log_path = os.path.join(comfyui_dir, "comfyui.log")
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            with open(log_path, "a", encoding="utf-8") as log_file:
                proc = subprocess.Popen(
                    cmd,
                    cwd=comfyui_dir,
                    env=env,
                    creationflags=creationflags,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )

        _SERVER_PROCESS = proc
        return True, f"ComfyUI server starting on port {port} (PID: {proc.pid})..."
    except Exception as e:
        _SERVER_STATE = "OFFLINE"
        _SERVER_START_TIME = 0.0
        return False, f"Failed to start ComfyUI server: {e}"


def stop_server(port: int = 8188) -> tuple[bool, str]:
    """Stop only the server process started by this add-on session."""
    global _SERVER_PROCESS, _SERVER_STATE, _SERVER_START_TIME

    _SERVER_STATE = "STOPPING"
    if _SERVER_PROCESS is not None:
        try:
            if _SERVER_PROCESS.poll() is None:
                _SERVER_PROCESS.terminate()
                try:
                    _SERVER_PROCESS.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    _SERVER_PROCESS.kill()
                    _SERVER_PROCESS.wait(timeout=3.0)
        except Exception as exc:
            _SERVER_STATE = "ONLINE" if is_server_alive(f"http://127.0.0.1:{port}") else "OFFLINE"
            return False, f"Could not stop the add-on's ComfyUI process: {exc}"
        _SERVER_PROCESS = None

    alive = is_server_alive(f"http://127.0.0.1:{port}", timeout=0.5)
    if not alive:
        _SERVER_STATE = "OFFLINE"
        _SERVER_START_TIME = 0.0
        return True, f"ComfyUI server is stopped on port {port}."
    else:
        _SERVER_STATE = "ONLINE"
        return False, "This ComfyUI server was started outside the current add-on session. Stop it in its launcher."
