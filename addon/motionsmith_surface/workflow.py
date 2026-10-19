"""Compile the installed PixelArtistry workflows into ComfyUI API prompts.

The JSON files own graph connections and widget defaults. Blender supplies its
mesh/camera inputs and overrides the settings exposed by the add-on. Optional
preview/postprocess branches, including Deep Bump's downloader, are excluded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


WORKFLOW_FILES = {
    "PBR_MATERIAL": "image_to_material.json",
    "6_VIEWS": "UltraTex - 1 Standard 6 views PBR.json",
    "10_VIEWS": "UltraTex - 2 Advanced 10 views PBR.json",
    "MANUAL_10_VIEWS": "UltraTex_Manual_10_Views_PBR.json",
    "LOW_VRAM_GGUF": "UltraTex - 3 Low VRAM GGUF.json",
}

# Widget serialization order from the installed node schemas. None denotes a
# frontend-only widget (upload button or control_after_generate).
_WIDGET_FIELDS = {
    "ChordLoadModel": ("ckpt_name",),
    "ChordMaterialEstimation": (),
    "ChordNormalToHeight": (),
    "LoadImage": ("image", None),
    "UltraTexLoadMesh": ("glb_path", "only_vertices_and_faces"),
    "LoadBackgroundRemovalModel": ("bg_removal_name",),
    "RemoveBackground": (),
    "UNETLoader": ("unet_name", "weight_dtype"),
    "UnetLoaderGGUF": ("unet_name",),
    "CLIPLoader": ("clip_name", "type", "device"),
    "CLIPLoaderGGUF": ("clip_name", "type"),
    "VAELoader": ("vae_name",),
    "UltraTexForegroundDecoder": ("decoder_name",),
    "UltraTexLoraLoader": ("lora_name", "strength"),
    "CLIPTextEncode": ("text",),
    "UltraTexTextEncode": ("text",),
    "UTXTextEncode": ("text",),
    "UltraTexPrep": ("mesh_path", "render_size", "atlas_size", "uv_mode", "reference_alignment", "mask_meaning"),
    "UltraTexSampler": ("resolution", "steps", "seed", None, "guidance", "drop_background_tokens", "memory_factor", "attention", "sparse_topk", "token_chunk", "denoise"),
    "UltraTexRotateRig": ("azimuth", "elevation", "elevation_mode"),
    "UltraTexRenderViews": ("resolution", "keep_above", "keep_feather", "texture"),
    "UltraTexBake": ("texture_size", "filename_prefix", "view_weight_power", "best_view_mix", "edge_feather_px", "views_2_use"),
    "ImageScale": ("upscale_method", "width", "height", "crop"),
    "ImageBatch": (),
    "Load3DAdvanced": ("model_file", "viewport_state", "width", "height"),
    "UTXFileToMesh": (),
    "UTXUnwrapMeshUVV25": ("atlas_size", "uv_mode", "padding"),
    "UTXPrepareTextureV25": ("alignment", "mask_polarity", "normal_mode"),
    "UTXGenerateTextureViewsV23": ("lora_name", "lora_strength", "decoder_name", "task", "view_resolution", "view_count", "seed", None, "steps", "guidance", "denoise", "sparse_retention", "extra_angle_mode", "extra_denoise", "extra_steps", "tiled_decode"),
    "UTXBakeTextureV26": ("texture_size", "fill_unseen", "blend_mode", "repair_mode"),
    "SaveGLB": ("filename_prefix",),
    "SaveImage": ("filename_prefix",),
}

_MODEL_DEFAULTS = {
    "unet_name": "flux-2-klein-base-9b-Q4_0.gguf",
    "clip_name": "qwen_3_8b_fp8mixed.safetensors",
    "vae_name": "flux2-vae.safetensors",
    "decoder_name": "ultratex_flux2_decoder.pt",
    "lora_albedo_name": "ultratex_flux2.safetensors",
    "lora_mr_name": "ultratex_flux2_mr.safetensors",
    "bg_removal_name": "birefnet.safetensors",
}


def workflow_directory(workflow_dir=None) -> Path:
    if workflow_dir:
        return Path(workflow_dir)
    return Path(__file__).resolve().parents[2] / "comfyui" / "user" / "default" / "workflows" / "PixelArtistry"


def _prune_graph(prompt, output_ids):
    needed = set()

    def visit(node_id):
        if node_id in needed:
            return
        if node_id not in prompt:
            raise ValueError(f"Workflow links to missing node {node_id}")
        needed.add(node_id)
        for value in prompt[node_id]["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                visit(value[0])

    for node_id in output_ids:
        visit(node_id)
    return {key: value for key, value in prompt.items() if key in needed}


def _load_prompt(workflow_id, workflow_dir):
    if workflow_id not in WORKFLOW_FILES:
        raise ValueError(f"Unknown UltraTex workflow: {workflow_id}")
    fname = WORKFLOW_FILES[workflow_id]
    
    candidate_paths = []
    # 1. Addon package bundled workflows/ directory (makes addon 100% self-contained)
    bundled_wf = Path(__file__).resolve().parent / "workflows"
    candidate_paths.append(bundled_wf / fname)
    # 2. Project root workflows/ directory (allows workspace custom overrides)
    root_wf = Path(__file__).resolve().parents[2] / "workflows"
    candidate_paths.append(root_wf / fname)
    # 3. Explicit workflow_dir passed from caller
    if workflow_dir:
        candidate_paths.append(Path(workflow_dir) / fname)
    # 4. ComfyUI default user workflows directory
    candidate_paths.append(Path(__file__).resolve().parents[2] / "comfyui" / "user" / "default" / "workflows" / "PixelArtistry" / fname)

    path = None
    for cp in candidate_paths:
        if cp.is_file():
            path = cp
            break
    if not path:
        raise FileNotFoundError(f"Workflow file not found: {fname}")

    with path.open("r", encoding="utf-8-sig") as handle:
        document = json.load(handle)
    if "nodes" not in document or "links" not in document:
        raise ValueError(f"Expected a ComfyUI UI workflow: {path}")
    source_nodes = {str(node["id"]): node for node in document["nodes"]}
    links = {link[0]: link for link in document["links"]}
    output_types = ({"SaveImage"} if workflow_id == "PBR_MATERIAL" else
                    {"SaveGLB", "SaveImage"} if workflow_id == "LOW_VRAM_GGUF" else {"UltraTexBake"})
    output_ids = [key for key, node in source_nodes.items() if node["type"] in output_types]
    if not output_ids:
        raise ValueError(f"Workflow has no texture/mesh output: {path}")
    # Traverse links first so optional previews cannot load models/downloaders.
    needed = set()

    def visit(node_id):
        if node_id in needed:
            return
        needed.add(node_id)
        for entry in source_nodes[node_id].get("inputs", []):
            link_id = entry.get("link")
            if link_id is not None:
                if link_id not in links:
                    raise ValueError(f"Missing workflow link {link_id} in {path.name}")
                visit(str(links[link_id][1]))

    for node_id in output_ids:
        visit(node_id)
    prompt = {}
    for node_id, source in source_nodes.items():
        if node_id not in needed:
            continue
        kind = source["type"]
        if kind not in _WIDGET_FIELDS:
            raise ValueError(f"Unsupported node {kind} in {path.name}; its settings cannot be mapped safely")
        inputs = {name: value for name, value in zip(_WIDGET_FIELDS[kind], source.get("widgets_values") or []) if name is not None}
        for entry in source.get("inputs", []):
            if entry.get("link") is not None:
                edge = links[entry["link"]]
                inputs[entry["name"]] = [str(edge[1]), int(edge[2])]
        prompt[node_id] = {"class_type": kind, "inputs": inputs, "_meta": {"title": source.get("title", kind)}}
    return prompt, output_ids


def _nodes(prompt, kind):
    return [(key, node) for key, node in prompt.items() if node["class_type"] == kind]


def build_material_prompt(image_name, checkpoint_name, output_prefix):
    """Compile image_to_material.json without mesh, camera or text inputs."""
    prompt, _ = _load_prompt("PBR_MATERIAL", None)
    for _, node in _nodes(prompt, "LoadImage"):
        node["inputs"]["image"] = image_name
    for _, node in _nodes(prompt, "ChordLoadModel"):
        node["inputs"]["ckpt_name"] = checkpoint_name
    for _, node in _nodes(prompt, "SaveImage"):
        suffix = node["inputs"]["filename_prefix"]
        node["inputs"]["filename_prefix"] = f"{output_prefix}/{suffix}"
    return prompt


def _select_loader(prompt, model_name, encoder_name):
    for _, node in list(prompt.items()):
        kind = node["class_type"]
        if kind in {"UNETLoader", "UnetLoaderGGUF"}:
            gguf = model_name.lower().endswith(".gguf")
            node["class_type"] = "UnetLoaderGGUF" if gguf else "UNETLoader"
            node["inputs"] = {"unet_name": model_name}
            if not gguf:
                node["inputs"]["weight_dtype"] = "default"
        elif kind in {"CLIPLoader", "CLIPLoaderGGUF"}:
            gguf = encoder_name.lower().endswith(".gguf")
            node["class_type"] = "CLIPLoaderGGUF" if gguf else "CLIPLoader"
            node["inputs"] = {"clip_name": encoder_name, "type": "flux2"}
            if not gguf:
                node["inputs"]["device"] = "default"


def build_workflow_prompt(
    workflow_id: str,
    mesh_path: str,
    view_image_names: List[str],
    workflow_dir=None,
    **settings,
) -> Dict[str, Any]:
    """Build one installed workflow using Blender's inputs and exposed settings.

    Manual captures: canonical front, left, back, right, top, bottom, followed
    by the rotated rig's front-left315, back-left225, back-right135, front-right45.
    These are actual rig slots, rather than ascending azimuth.

    Blender references have transparent backgrounds, used directly as masks.
    Set reference_is_render=False to use the workflow's BiRefNet branch.
    """
    manual = workflow_id == "MANUAL_10_VIEWS"
    input_mode = "BOTH" if manual else settings.get("input_mode", "BOTH")
    if input_mode not in {"PROMPT", "IMAGE", "BOTH"}:
        raise ValueError(f"Unknown input mode: {input_mode}")
    use_reference = input_mode != "PROMPT"
    use_text = input_mode != "IMAGE"
    if use_reference and not view_image_names:
        raise ValueError("Image input mode requires a reference image or camera capture")
    if workflow_id == "MANUAL_10_VIEWS" and len(view_image_names) != 10:
        raise ValueError(f"Manual UltraTex requires 10 calibrated images; got {len(view_image_names)}")
    prompt, output_ids = _load_prompt(workflow_id, workflow_dir)
    models = {key: str(settings.get(key, default)).replace("/", os.sep) for key, default in _MODEL_DEFAULTS.items()}
    _select_loader(prompt, models["unet_name"], models["clip_name"])
    steps = int(settings.get("steps", 20))
    resolution = int(settings.get("view_resolution", 1024))
    mr_resolution = int(settings.get("mr_resolution", resolution))
    mr_steps = int(settings.get("mr_steps") or steps)
    texture_size = int(settings.get("texture_size", 2048))
    enable_mr = bool(settings.get("enable_mr", True))
    if (workflow_id != "MANUAL_10_VIEWS" or enable_mr) and float(settings.get("albedo_denoise", 1.0)) != 1.0:
        raise ValueError("The first pass has no init views and requires denoise 1.0; use Pass 2 Denoise for refinement")
    if workflow_id == "LOW_VRAM_GGUF":
        active_steps = [steps, int(settings.get("extra_steps", steps))]
        if enable_mr:
            active_steps.append(mr_steps)
        if any(value > 100 for value in active_steps):
            raise ValueError("The installed GGUF Generate Views node supports at most 100 steps")
    output_prefix = settings.get("output_prefix", "UltraTex/mesh")
    image_nodes = _nodes(prompt, "LoadImage")
    if workflow_id == "MANUAL_10_VIEWS":
        # JSON's ascending-angle labels contradict UltraTexRotateRig's OBJECT
        # rotation. Supply the inverse camera rotation to its unchanged batches.
        image_ids = ["1", "31", "32", "33", "34", "35", "36", "37", "38", "39"]
        labels = ["Front 0", "Left 270", "Back 180", "Right 90", "Top", "Bottom", "Front-left 315", "Back-left 225", "Back-right 135", "Front-right 45"]
        for node_id, filename, label in zip(image_ids, view_image_names, labels):
            if node_id not in prompt or prompt[node_id]["class_type"] != "LoadImage":
                raise ValueError("Manual workflow camera nodes changed; review its camera/batch mapping")
            prompt[node_id]["inputs"]["image"] = filename
            prompt[node_id]["_meta"]["title"] = label
        reference_id = image_ids[0]
    elif use_reference:
        reference_id, reference = image_nodes[0]
        reference["inputs"]["image"] = view_image_names[0]
    else:
        reference_id = None

    for _, node in _nodes(prompt, "UltraTexLoadMesh"):
        node["inputs"].update(glb_path=os.path.abspath(mesh_path), only_vertices_and_faces=False)
    for _, node in _nodes(prompt, "Load3DAdvanced"):
        # ComfyUI Load3D expects relative path inside input/ (e.g. "3d/MotionSmith_Surface/.../target.obj")
        norm_mesh = os.path.abspath(mesh_path).replace("\\", "/")
        if "/input/" in norm_mesh:
            rel_3d = norm_mesh.split("/input/", 1)[1]
        else:
            rel_3d = norm_mesh
        node["inputs"].update(model_file=rel_3d, viewport_state={"camera_info": {}}, width=512, height=512)
    for _, node in _nodes(prompt, "VAELoader"):
        node["inputs"]["vae_name"] = models["vae_name"]
    for _, node in _nodes(prompt, "UltraTexForegroundDecoder"):
        node["inputs"]["decoder_name"] = models["decoder_name"]
    for node_id, node in _nodes(prompt, "UltraTexLoraLoader"):
        mr = node_id == "11"
        node["inputs"].update(lora_name=models["lora_mr_name" if mr else "lora_albedo_name"], strength=float(settings.get("lora_mr_strength" if mr else "lora_albedo_strength", 1.0)))
    for _, node in _nodes(prompt, "LoadBackgroundRemovalModel"):
        node["inputs"]["bg_removal_name"] = models["bg_removal_name"]

    reference_is_render = bool(settings.get("reference_is_render", True))
    for _, node in _nodes(prompt, "UltraTexPrep"):
        node["inputs"].update(render_size=int(settings.get("render_size", 4096)), atlas_size=texture_size, uv_mode=settings.get("uv_mode", "comfy_gpu"), reference_alignment=settings.get("reference_alignment", "fit_front_silhouette"))
        if not use_reference:
            node["inputs"].pop("reference_image", None)
            node["inputs"].pop("reference_mask", None)
        elif reference_is_render:
            node["inputs"].update(reference_mask=[reference_id, 1], mask_meaning="background (LoadImage)")
        elif "mask_meaning" in settings:
            node["inputs"]["mask_meaning"] = settings["mask_meaning"]
    for _, node in _nodes(prompt, "ImageScale"):
        node["inputs"].update(width=resolution, height=resolution)

    # Distinct negative conditioning enables FLUX.2 text CFG. Opt in explicitly
    # instead of presenting a negative prompt that the sampler silently ignores.
    text_nodes = [(key, node) for key, node in prompt.items() if node["class_type"] in {"CLIPTextEncode", "UltraTexTextEncode", "UTXTextEncode"}]
    for _, node in text_nodes:
        node["inputs"]["text"] = settings.get("positive_prompt", "") if use_text else ""
    negative_by_positive = {}
    if use_text and settings.get("use_negative_prompt", False):
        for positive_id, positive in text_nodes:
            negative_id = str(max([int(key) for key in prompt if key.isdigit()] + [100]) + 1)
            prompt[negative_id] = {"class_type": positive["class_type"], "inputs": {"clip": positive["inputs"]["clip"], "text": settings.get("negative_prompt", "")}, "_meta": {"title": "Negative Prompt (CFG)"}}
            negative_by_positive[positive_id] = [negative_id, 0]

    for node_id, node in _nodes(prompt, "UltraTexSampler"):
        mr = node_id == "20"
        second = node_id == "24"
        node["_meta"]["title"] = ("Metallic / Roughness" if mr else "Albedo refinement" if second else "Albedo generation")
        node["inputs"].update(resolution=mr_resolution if mr else resolution, steps=mr_steps if mr else steps, seed=int(settings.get("seed", 42)), guidance=float(settings.get("guidance", 4.0)))
        for name, default in (("drop_background_tokens", True), ("memory_factor", 0.0), ("attention", "ultratex_sparse"), ("sparse_topk", 0.2), ("token_chunk", 8192)):
            node["inputs"][name] = settings.get(name, default)
        node["inputs"]["denoise"] = float(settings.get("multiview_denoise", 0.6) if second else settings.get("albedo_denoise", 1.0))
        positive_id = node["inputs"]["positive"][0]
        if positive_id in negative_by_positive:
            node["inputs"]["negative"] = negative_by_positive[positive_id]
        else:
            node["inputs"].pop("negative", None)
    for _, node in _nodes(prompt, "UltraTexRenderViews"):
        node["inputs"].update(resolution=resolution, keep_above=float(settings.get("keep_above", 0.75)), keep_feather=float(settings.get("keep_feather", 0.1)))
    for _, node in _nodes(prompt, "UltraTexBake"):
        node["inputs"].update(texture_size=texture_size, filename_prefix=output_prefix, view_weight_power=float(settings.get("view_weight_power", 4.0)), best_view_mix=float(settings.get("best_view_mix", 0.5)), edge_feather_px=float(settings.get("edge_feather_px", 6.0)))
        if not enable_mr:
            node["inputs"].pop("metallic_roughness_views", None)
            node["inputs"].pop("metallic_roughness_views_2", None)

    if workflow_id == "LOW_VRAM_GGUF":
        for _, node in _nodes(prompt, "UTXUnwrapMeshUVV25"):
            node["inputs"].update(atlas_size=texture_size, uv_mode=settings.get("uv_mode", "comfy_gpu"), padding=int(settings.get("uv_padding", 16)))
        for _, node in _nodes(prompt, "UTXPrepareTextureV25"):
            node["inputs"]["alignment"] = "front" if settings.get("reference_alignment", "fit_front_silhouette") == "fit_front_silhouette" else "center"
            if not use_reference:
                node["inputs"].pop("reference", None)
                node["inputs"].pop("mask", None)
            elif reference_is_render:
                node["inputs"].update(mask=[reference_id, 1], mask_polarity="background")
        for _, node in _nodes(prompt, "UTXGenerateTextureViewsV23"):
            mr = node["inputs"]["task"] == "mr"
            node["inputs"].update(lora_name=models["lora_mr_name" if mr else "lora_albedo_name"], lora_strength=float(settings.get("lora_mr_strength" if mr else "lora_albedo_strength", 1.0)), decoder_name=models["decoder_name"], view_resolution=mr_resolution if mr else resolution, view_count=6 if mr else int(settings.get("view_count", 12)), steps=mr_steps if mr else steps, seed=int(settings.get("seed", 42)), guidance=float(settings.get("guidance", 4.0)), denoise=float(settings.get("albedo_denoise", 1.0)), sparse_retention=float(settings.get("sparse_topk", 0.2)), extra_denoise=max(0.1, float(settings.get("multiview_denoise", 0.6))), extra_steps=int(settings.get("extra_steps", steps)), extra_angle_mode=settings.get("extra_angle_mode", "guided"), tiled_decode=bool(settings.get("tiled_decode", True)))
            positive_id = node["inputs"]["positive"][0]
            if positive_id in negative_by_positive:
                node["inputs"]["negative"] = negative_by_positive[positive_id]
            else:
                node["inputs"].pop("negative", None)
        for _, node in _nodes(prompt, "UTXBakeTextureV26"):
            node["inputs"].update(texture_size=texture_size, fill_unseen=bool(settings.get("fill_unseen", True)), blend_mode=settings.get("blend_mode", "detail_preserving"), repair_mode=settings.get("repair_mode", "normal_aware_surface"))
            if not enable_mr:
                node["inputs"].pop("mr_views", None)
                node["inputs"].pop("mr_setup", None)
        for _, node in _nodes(prompt, "SaveGLB"):
            node["inputs"]["filename_prefix"] = output_prefix
            node["_meta"]["title"] = "Textured Mesh GLB"
            # SaveGLB in older ComfyUI can save MESH albedo only. The bake's
            # FILE_3D_GLB output already contains the complete ORM material.
            mesh_link = node["inputs"].get("mesh")
            if isinstance(mesh_link, list) and prompt.get(mesh_link[0], {}).get("class_type") == "UTXBakeTextureV26":
                node["inputs"]["mesh"] = [mesh_link[0], 4]
        for node_id, node in _nodes(prompt, "SaveImage"):
            map_name = {"14": "albedo", "22": "roughness", "23": "metallic"}.get(node_id, "map")
            node["inputs"]["filename_prefix"] = f"{output_prefix}_{map_name}"
            node["_meta"]["title"] = f"{map_name.title()} Texture"
        if not enable_mr:
            output_ids = [node_id for node_id in output_ids if node_id not in {"22", "23"}]
    return _prune_graph(prompt, output_ids)


_LEGACY_ARGUMENTS = (
    "positive_prompt", "negative_prompt", "unet_name", "clip_name", "vae_name",
    "decoder_name", "lora_albedo_name", "lora_mr_name", "bg_removal_name",
    "steps", "guidance", "view_resolution", "texture_size", "seed", "uv_mode",
    "reference_alignment", "mask_meaning", "lora_albedo_strength",
    "lora_mr_strength", "view_weight_power", "best_view_mix", "edge_feather_px",
    "output_prefix",
)


def _legacy_settings(args, settings, advanced=False):
    names = _LEGACY_ARGUMENTS
    if advanced:
        names = names[:17] + ("multiview_denoise",) + names[17:]
    if len(args) > len(names):
        raise TypeError("Too many positional workflow arguments")
    for name, value in zip(names, args):
        if name in settings:
            raise TypeError(f"Multiple values for workflow argument '{name}'")
        settings[name] = value
    return settings


def build_single_view_prompt(mesh_path, reference_image_name, *args, **settings):
    settings = _legacy_settings(args, settings)
    return build_workflow_prompt("6_VIEWS", mesh_path, [reference_image_name], **settings)


def build_multiview_prompt(mesh_path, view_image_names, *args, **settings):
    settings = _legacy_settings(args, settings, advanced=True)
    return build_workflow_prompt("10_VIEWS", mesh_path, view_image_names, **settings)


def build_manual_multiview_prompt(mesh_path, view_image_names, **settings):
    return build_workflow_prompt("MANUAL_10_VIEWS", mesh_path, view_image_names, **settings)


def build_low_vram_prompt(mesh_path, view_image_names, **settings):
    return build_workflow_prompt("LOW_VRAM_GGUF", mesh_path, view_image_names, **settings)


build_ultratex_prompt = build_single_view_prompt
