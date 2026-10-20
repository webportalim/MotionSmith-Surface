"""Build a model-free Windows backend from the verified local Python runtime.

Run with comfyui/.venv/Scripts/python.exe. The output contains real files,
never the workspace's environment/models junctions or personal input/output.
"""

import argparse
import hashlib
import importlib.metadata as metadata
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent
COMFY = ROOT / "comfyui"
NODES = ("ComfyUI-UltraTex", "comfyui_ultratex_modular", "ComfyUI-Chord", "ComfyUI-GGUF", "comfy-mtb")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
WEIGHTS = {".safetensors", ".gguf", ".ckpt", ".pt", ".onnx", ".pth"}


def walk_files(root):
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in list(dirs):
            path = Path(directory) / name
            if path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError(f"Unexpected directory link: {path}")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() in {".pyc", ".pyo", ".log"}:
                continue
            if path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError(f"Unexpected file link: {path}")
            yield path


def runtime_distributions():
    roots = [line.strip() for line in (COMFY / "requirements.txt").read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    roots += ["trimesh", "xatlas", "moderngl", "glcontext", "gguf", "diffusers", "imageio",
              "omegaconf", "timm", "accelerate", "triton-windows", "setuptools", "packaging",
              "onnxruntime-gpu", "requirements-parser"]
    distributions = {}
    pending = [(Requirement(text), "") for text in roots]
    expanded = set()
    while pending:
        requirement, parent_extra = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({"extra": parent_extra}):
            continue
        name = canonicalize_name(requirement.name)
        dist = distributions.get(name) or metadata.distribution(requirement.name)
        distributions[name] = dist
        for extra in {"", *requirement.extras}:
            if (name, extra) in expanded:
                continue
            expanded.add((name, extra))
            for dependency in dist.requires or []:
                pending.append((Requirement(dependency), extra))
    return distributions


def add_file(files, destination, source, allow_path_config=False):
    source = Path(source)
    if not source.is_file() or source.suffix.lower() in {".pyc", ".pyo"}:
        return
    if source.suffix.lower() in WEIGHTS:
        # Python .pth path configuration is not a model weight.
        if not (allow_path_config and source.suffix.lower() == ".pth" and source.stat().st_size < 16384):
            raise ValueError(f"Model file would enter backend: {source}")
        text = source.read_text(encoding="utf-8")
        if any(os.path.isabs(line.strip()) for line in text.splitlines() if line.strip() and not line.startswith(("#", "import "))):
            raise ValueError(f"Non-portable Python path configuration: {source}")
    if destination in files and files[destination] != source:
        raise ValueError(f"Duplicate archive destination: {destination}")
    files[destination] = source


def collect_files():
    if sys.version_info[:3] != (3, 12, 10) or sys.platform != "win32":
        raise RuntimeError("Build with the verified Windows Python 3.12.10 environment.")
    files = {}
    excluded = {"custom_nodes", "input", "output", "temp", "user", "models", "styles", *SKIP_DIRS}
    for child in COMFY.iterdir():
        if child.name in excluded or child.suffix.lower() == ".log":
            continue
        if child.is_dir():
            for path in walk_files(child):
                add_file(files, "comfyui/" + path.relative_to(COMFY).as_posix(), path)
        elif child.is_file():
            add_file(files, "comfyui/" + child.name, child)
    # Preserve the upstream license alongside the redistributed core sources.
    license_path = COMFY / "LICENSE"
    if not license_path.is_file():
        license_path = Path(sys.prefix).resolve().parent / "LICENSE"
    if not license_path.is_file():
        raise FileNotFoundError("ComfyUI LICENSE must be present before packaging")
    add_file(files, "comfyui/LICENSE", license_path)
    for name in NODES:
        node = COMFY / "custom_nodes" / name
        for path in walk_files(node):
            add_file(files, "comfyui/" + path.relative_to(COMFY).as_posix(), path)
    base = Path(sys.base_prefix)
    for name in ("python.exe", "pythonw.exe", "python3.dll", "python312.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        add_file(files, "comfyui/.venv/Scripts/" + name, base / name)
    for name in ("DLLs", "include", "libs"):
        for path in walk_files(base / name):
            add_file(files, "comfyui/.venv/Scripts/" + path.relative_to(base).as_posix(), path)
    distributions = runtime_distributions()
    for dist in distributions.values():
        site = Path(dist.locate_file("")).resolve()
        for entry in dist.files or []:
            path = Path(os.path.abspath(site / entry))
            if not path.is_relative_to(site):
                continue  # Never copy launchers with absolute interpreter paths.
            relative = path.relative_to(site)
            if path.suffix.lower() in WEIGHTS and path.suffix.lower() != '.pth':
                continue  # Runtime wheels may contain sample models; keep the backend model-free.
            add_file(files, "comfyui/.venv/Lib/site-packages/" + relative.as_posix(), path,
                     allow_path_config=True)
    return files, distributions, base


def build(inventory=False):
    files, distributions, base = collect_files()
    size = sum(path.stat().st_size for path in files.values())
    print(f"Selected {len(files)} files, {len(distributions)} distributions, {size / 1024**3:.2f} GiB", flush=True)
    if inventory:
        return
    destination = ROOT / "motionsmith_surface_backend_win64_0.1.1.zip"
    temporary = destination.with_suffix(".zip.partial")
    stdlib = io.BytesIO()
    with zipfile.ZipFile(stdlib, "w", zipfile.ZIP_DEFLATED) as lib:
        for path in walk_files(base / "Lib"):
            relative = path.relative_to(base / "Lib")
            if any(part in {"site-packages", "test", "tests", "idlelib", "tkinter", "ensurepip"} for part in relative.parts):
                continue
            if path.suffix.lower() in {".py", ".json", ".txt", ".pem"}:
                lib.write(path, relative.as_posix())
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
        for index, (name, path) in enumerate(sorted(files.items()), 1):
            archive.write(path, name)
            if index % 5000 == 0:
                print(f"Packed {index}/{len(files)} files", flush=True)
        archive.writestr("comfyui/.venv/Scripts/python312.zip", stdlib.getvalue())
        archive.writestr("comfyui/.venv/Scripts/python312._pth",
                         "python312.zip\n.\nDLLs\n..\\Lib\\site-packages\n..\\..\nimport site\n")
        versions = {name: dist.version for name, dist in sorted(distributions.items())}
        archive.writestr("comfyui/runtime_versions.json", json.dumps({
            "python": "3.12.10", "models_included": False, "custom_nodes": NODES,
            "distributions": versions,
        }, indent=2))
        for folder in ("input", "output", "temp", "models/checkpoints/SD", "models/diffusion_models",
                       "models/text_encoders", "models/vae", "models/loras", "models/ultratex",
                       "models/background_removal"):
            archive.writestr(f"comfyui/{folder}/", "")
        # Bundle the UI graphs without optional preview/downloader branches.
        for source in (ROOT / "addon/motionsmith_surface/workflows").glob("*.json"):
            if source.name not in {"image_to_material.json", "UltraTex - 1 Standard 6 views PBR.json",
                                   "UltraTex - 2 Advanced 10 views PBR.json",
                                   "UltraTex - 3 Low VRAM GGUF.json", "UltraTex_Manual_10_Views_PBR.json"}:
                continue
            doc = json.loads(source.read_text(encoding="utf-8-sig"))
            nodes = {node["id"]: node for node in doc["nodes"]}
            links = {link[0]: link for link in doc["links"]}
            output_types = {"SaveImage"} if source.name == "image_to_material.json" else (
                {"SaveGLB", "SaveImage"} if "Low VRAM" in source.name else {"UltraTexBake"})
            needed = set()
            def visit(node_id):
                if node_id in needed:
                    return
                needed.add(node_id)
                for entry in nodes[node_id].get("inputs", []):
                    if entry.get("link") is not None:
                        visit(links[entry["link"]][1])
            for node_id, node in nodes.items():
                if node["type"] in output_types:
                    visit(node_id)
            doc["nodes"] = [node for node in doc["nodes"] if node["id"] in needed]
            doc["links"] = [link for link in doc["links"] if link[1] in needed and link[3] in needed]
            for node in doc["nodes"]:
                for output in node.get("outputs", []):
                    if output.get("links") is not None:
                        output["links"] = [link for link in output["links"] if any(edge[0] == link for edge in doc["links"])]
            archive.writestr("comfyui/user/default/workflows/PixelArtistry/" + source.name, json.dumps(doc, indent=2))
    with zipfile.ZipFile(temporary) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Archive integrity check failed: {bad}")
    temporary.replace(destination)
    with destination.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    destination.with_suffix(".zip.sha256").write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    print(f"BACKEND_READY {destination} ({destination.stat().st_size / 1024**3:.2f} GiB) SHA256={digest}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", action="store_true")
    build(parser.parse_args().inventory)
