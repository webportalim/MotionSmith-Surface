"""MotionSmith Surface - ComfyUI Client API."""

import urllib.request
import urllib.error
import urllib.parse
import json
import os
import time
import threading
import uuid
import sys


class ComfyUIClient:
    def __init__(self, server_url: str = "http://127.0.0.1:8188"):
        self.server_url = server_url.rstrip("/")
        self.client_id = "motionsmith_surface_" + uuid.uuid4().hex
        self.progress = {}
        self._progress_stop = threading.Event()
        self._progress_socket = None

    def _start_progress(self):
        """Subscribe before queueing so even cached/fast nodes are observed."""
        try:
            try:
                import websocket
            except ImportError:
                # Legacy Blender add-on installs do not activate manifest wheels.
                wheel = os.path.join(os.path.dirname(__file__), "wheels", "websocket_client-1.8.0-py3-none-any.whl")
                if wheel not in sys.path:
                    sys.path.insert(0, wheel)
                import websocket
            url = self.server_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
            self._progress_socket = websocket.create_connection(
                f"{url}/ws?clientId={self.client_id}", timeout=2)
        except Exception:
            self.progress = {"unavailable": True}
            return
        def receive():
            try:
                while not self._progress_stop.is_set():
                    try:
                        message = self._progress_socket.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not message:
                        break
                    if isinstance(message, str):
                        event = json.loads(message)
                        self._record_progress(event.get("type"), event.get("data", {}))
            except Exception:
                if not self._progress_stop.is_set():
                    self.progress = {**self.progress, "unavailable": True}
            finally:
                if not self._progress_stop.is_set():
                    self.progress = {**self.progress, "unavailable": True}
        threading.Thread(target=receive, daemon=True).start()

    def _record_progress(self, kind, data):
        now = time.time()
        old = self.progress
        if kind == "execution_start":
            self.progress = {"prompt_id": data.get("prompt_id"), "started": now}
        elif kind == "executing" and data.get("node") is not None:
            self.progress = {"prompt_id": data.get("prompt_id"), "node": str(data["node"]), "started": now}
        elif kind == "progress":
            node = str(data.get("node"))
            value, total = float(data.get("value", 0)), float(data.get("max", 0))
            same = (old.get("node") == node and old.get("prompt_id") == data.get("prompt_id")
                    and old.get("total", total) == total and value >= old.get("value", 0))
            baseline = old.get("baseline") if same else None
            if baseline is None and value > 0:
                baseline = (value, now)
            self.progress = {"prompt_id": data.get("prompt_id"), "node": node,
                             "value": value, "total": total, "baseline": baseline,
                             "started": old.get("started", now) if same else now}

    def close_progress(self):
        self._progress_stop.set()
        if self._progress_socket is not None:
            try:
                self._progress_socket.close(timeout=0)
            except Exception:
                pass

    def is_connected(self, timeout: float = 2.0) -> bool:
        """Check if server is reachable and responsive."""
        try:
            req = urllib.request.Request(f"{self.server_url}/system_stats")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def get_system_stats(self) -> dict | None:
        """Get system stats."""
        try:
            req = urllib.request.Request(f"{self.server_url}/system_stats")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def queue_prompt(self, prompt: dict, client_id: str | None = None) -> tuple[bool, str, dict]:
        """Send prompt graph to ComfyUI /prompt endpoint.
        Returns: (success, message, response_data)
        """
        if client_id:
            self.client_id = client_id
        self._start_progress()
        url = f"{self.server_url}/prompt"
        payload = {
            "prompt": prompt,
            "client_id": self.client_id,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                prompt_id = res.get("prompt_id", "")
                node_errors = res.get("node_errors", {})
                if node_errors:
                    self.close_progress()
                    return False, f"Workflow validation errors: {json.dumps(node_errors)}", res
                return True, prompt_id, res
        except urllib.error.HTTPError as e:
            self.close_progress()
            err_msg = e.read().decode("utf-8")
            return False, f"ComfyUI HTTP {e.code}: {err_msg}", {}
        except Exception as e:
            self.close_progress()
            return False, f"Connection failed: {e}", {}

    def get_history(self, prompt_id: str) -> dict | None:
        """Get execution history for a given prompt_id."""
        url = f"{self.server_url}/history/{prompt_id}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get(prompt_id)
        except Exception:
            return None

    def get_queue(self) -> dict | None:
        """Get current queue status."""
        url = f"{self.server_url}/queue"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def interrupt(self) -> bool:
        """Interrupt active execution."""
        url = f"{self.server_url}/interrupt"
        try:
            req = urllib.request.Request(url, data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def poll_execution(self, prompt_id: str, timeout: float = 300.0, interval: float = 2.0, callback=None) -> tuple[bool, str, dict]:
        """Poll ComfyUI until prompt execution finishes or times out.
        Returns: (success, message, outputs_dict)
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            history = self.get_history(prompt_id)
            if history:
                status = history.get("status", {})
                completed = status.get("completed", False)
                status_str = status.get("status_str", "")

                messages = status.get("messages", [])
                for msg in messages:
                    if msg[0] in {"execution_error", "execution_interrupted"}:
                        details = msg[1]
                        self.close_progress()
                        return False, f"{details.get('node_type', 'Workflow')}: {details.get('exception_message', msg[0]).strip()}", {}

                if completed or status_str == "success":
                    self.close_progress()
                    return True, "Execution completed successfully.", history.get("outputs", {})

            elapsed = int(time.time() - start_time)
            if callback:
                callback(elapsed)

            time.sleep(interval)

        self.close_progress()
        return False, f"Execution timed out after {timeout} seconds.", {}

    def cancel_prompt(self, prompt_id):
        queue = self.get_queue() or {}
        pending = any(item[1] == prompt_id for item in queue.get("queue_pending", []))
        if pending:
            req = urllib.request.Request(
                f"{self.server_url}/queue", data=json.dumps({"delete": [prompt_id]}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=3):
                    return True
            except (OSError, urllib.error.URLError):
                return False
        if any(item[1] == prompt_id for item in queue.get("queue_running", [])):
            return self.interrupt()
        return False

    @staticmethod
    def validate_local_models(prompt, comfyui_dir):
        categories = {
            "ckpt_name": ("checkpoints",),
            "unet_name": ("diffusion_models", "unet"),
            "clip_name": ("text_encoders", "clip"),
            "vae_name": ("vae",), "decoder_name": ("ultratex",),
            "lora_name": ("loras",), "bg_removal_name": ("background_removal",)}
        for node in prompt.values():
            for name, value in node.get("inputs", {}).items():
                if name == "auto_download" and value:
                    raise ValueError("This workflow enables a model download. Disable it before running.")
                if name not in categories or not isinstance(value, str):
                    continue
                relative = value.replace("\\", os.sep).replace("/", os.sep)
                if value == "__MISSING__" or not any(
                    os.path.isfile(os.path.join(comfyui_dir, "models", category, relative))
                    for category in categories[name]):
                    raise FileNotFoundError(f"Installed model not found: {name} = {value}")

    @staticmethod
    def resolve_bake_outputs(outputs, prompt, comfyui_dir):
        """Use this prompt's output records, never the newest file in a directory."""
        root = os.path.realpath(os.path.join(comfyui_dir, "output"))
        def path_for(descriptor):
            if descriptor.get("type", "output") != "output":
                raise ValueError("The workflow did not return a persistent output.")
            path = os.path.realpath(os.path.join(
                root, descriptor.get("subfolder", ""), descriptor["filename"]))
            if os.path.commonpath([root, path]) != root or not os.path.isfile(path):
                raise FileNotFoundError(f"Workflow output is missing: {path}")
            return path
        result = {}
        for node_id, output in outputs.items():
            node = (prompt or {}).get(str(node_id), {})
            if not isinstance(output, dict):
                continue
            for record in output.get("3d", []):
                if record.get("filename", "").lower().endswith(".glb"):
                    result["glb"] = path_for(record)
                    stem = os.path.splitext(result["glb"])[0]
                    if os.path.isfile(stem + "_albedo.png"):
                        result["albedo"] = stem + "_albedo.png"
                    if os.path.isfile(stem + "_orm.png"):
                        result["orm"] = stem + "_orm.png"
                    if os.path.isfile(stem + "_normal.png"):
                        result["normal"] = stem + "_normal.png"
            if node.get("class_type") == "SaveImage":
                label = node.get("_meta", {}).get("title", "").lower()
                for record in output.get("images", []):
                    text = label + " " + record.get("filename", "").lower()
                    kind = next((kind for kind in ("roughness", "metallic", "albedo", "normal", "height")
                                 if kind in text), None)
                    if not kind and any(word in text for word in ("base_color", "base color", "basecolor")):
                        kind = "albedo"
                    if not kind and "metalness" in text:
                        kind = "metallic"
                    if kind:
                        result[kind] = path_for(record)
        chord = any(node.get("class_type") == "ChordMaterialEstimation" for node in (prompt or {}).values())
        required_maps = ("albedo", "normal", "roughness", "metallic", "height") if chord else ("glb", "albedo")
        for required in required_maps:
            if not result.get(required) or not os.path.isfile(result[required]):
                raise FileNotFoundError(f"This prompt returned no usable {required} output: {result.get(required)}")
        return result
