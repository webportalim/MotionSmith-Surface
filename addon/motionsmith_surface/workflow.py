"""Compile the installed PixelArtistry workflows into ComfyUI API prompts.

The JSON files own graph connections and widget defaults. Blender supplies its
mesh/camera inputs and overrides the settings exposed by the add-on. Optional
preview branches and automatic model downloads are excluded. Detail normals
and baked-atlas PBR estimation are attached explicitly after the final UV bake.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


WORKFLOW_FILES = {
    "PBR_MATERIAL": "image_to_material.json",
    "PBR_PROMPT": "Flux2_image_to_material.json",
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
    "ModelSamplingAuraFlow": ("shift",),
    "ConditioningZeroOut": (),
    "VAEDecode": (),
    "KSampler": ("seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"),
    "EmptySD3LatentImage": ("width", "height", "batch_size"),
    "ResizeAndPadImage": ("target_width", "target_height", "padding_color", "interpolation"),
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
    output_types = ({"SaveImage"} if workflow_id in {"PBR_MATERIAL", "PBR_PROMPT"} else
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


_PBR_PROMPT_FIELDS = {
    "prompt": ("4", "text"),
    "unet_name": ("1", "unet_name"), "weight_dtype": ("1", "weight_dtype"),
    "clip_name": ("3", "clip_name"), "clip_type": ("3", "type"), "clip_device": ("3", "device"),
    "vae_name": ("8", "vae_name"), "checkpoint": ("12", "ckpt_name"),
    "shift": ("2", "shift"),
    "seed": ("7", "seed"), "steps": ("7", "steps"), "cfg": ("7", "cfg"),
    "sampler_name": ("7", "sampler_name"), "scheduler": ("7", "scheduler"),
    "denoise": ("7", "denoise"),
    "width": ("6", "width"), "height": ("6", "height"), "batch_size": ("6", "batch_size"),
    "map_width": ("11", "target_width"), "map_height": ("11", "target_height"),
    "padding_color": ("11", "padding_color"), "interpolation": ("11", "interpolation"),
    "texture_prefix": ("10", "filename_prefix"), "basecolor_prefix": ("14", "filename_prefix"),
    "normal_prefix": ("15", "filename_prefix"), "metalness_prefix": ("16", "filename_prefix"),
    "roughness_prefix": ("17", "filename_prefix"), "height_prefix": ("19", "filename_prefix"),
}


def _add_detail_normal(prompt, image_link, output_prefix):
    prompt['surface_deepbump'] = {
        'class_type': 'Deep Bump (mtb)',
        'inputs': dict(image=image_link, mode='Color to Normals', color_to_normals_overlap='MEDIUM',
                       normals_to_curvature_blur_radius='SMALLEST', normals_to_height_seamless=True,
                       auto_download=False),
        '_meta': {'title': 'Generate texture detail normal'},
    }
    prompt['surface_normal'] = {
        'class_type': 'SaveImage',
        'inputs': {'images': ['surface_deepbump', 0], 'filename_prefix': output_prefix + '_normal'},
        '_meta': {'title': 'Surface Normal', 'surface_map': 'normal'},
    }
    return 'surface_normal'


def _add_mesh_pbr_maps(prompt, image_link, output_prefix, checkpoint):
    prompt['surface_chord'] = {
        'class_type': 'ChordLoadModel',
        'inputs': {'ckpt_name': str(checkpoint or 'SD/chord_v1.safetensors').replace('/', os.sep).replace('\\', os.sep)},
    }
    prompt['surface_estimate'] = {
        'class_type': 'ChordMaterialEstimation',
        'inputs': {'chord_model': ['surface_chord', 0], 'image': image_link},
        '_meta': {'title': 'Estimate PBR maps from baked UV texture'},
    }
    prompt['surface_height'] = {
        'class_type': 'ChordNormalToHeight', 'inputs': {'normal': ['surface_estimate', 1]},
    }
    for name, link in (('normal', ['surface_estimate', 1]), ('roughness', ['surface_estimate', 2]),
                       ('metallic', ['surface_estimate', 3]), ('height', ['surface_height', 0])):
        prompt['surface_save_' + name] = {
            'class_type': 'SaveImage',
            'inputs': {'images': link, 'filename_prefix': output_prefix + '_' + name},
            '_meta': {'title': 'Surface ' + name.title(), 'surface_map': name},
        }


def build_mesh_basecolor_prompt(mesh_path, reference_image_name, output_prefix, transfer, *,
                               steps=25, view_size=512, texture_size=2048, seed=1024, checkpoint=None):
    """Paint an existing UV mesh and derive PBR maps from its final baked atlas."""
    with open(Path(__file__).with_name('workflows') / 'hy3d_mesh_basecolor.json', encoding='utf-8') as handle:
        prompt = json.load(handle)
    if not os.path.isfile(mesh_path):
        raise FileNotFoundError("The validated transfer GLB is missing. Run T1/T2 again.")
    if not 0 <= int(seed) <= 0xffffffffffffffff:
        raise ValueError("Seed must be between 0 and 18446744073709551615.")
    if int(view_size) not in (512, 1024) or int(texture_size) not in (1024, 2048, 4096) or not 1 <= int(steps) <= 100:
        raise ValueError("Unsupported mesh-paint resolution or step count.")
    prompt['1']['inputs']['glb_path'] = os.path.abspath(mesh_path)
    prompt['2']['inputs']['image'] = reference_image_name
    prompt['3']['inputs'].update(target_width=int(view_size), target_height=int(view_size))
    prompt['5']['inputs']['texture_size'] = int(texture_size)
    prompt['8']['inputs'].update(view_size=int(view_size), steps=int(steps), seed=int(seed))
    prompt['9']['inputs'].update(width=int(texture_size), height=int(texture_size))
    prompt['13']['inputs']['filename_prefix'] = output_prefix
    prompt['13']['_meta']['surface_transfer'] = dict(
        directory=transfer['directory'], fingerprint=transfer['fingerprint'],
        uv_name=transfer['uv_name'], glb_hash=transfer['glb_hash'])
    for node_id, name in (('14', 'paint_views'), ('15', 'initial_bake'), ('17', 'bake_coverage')):
        prompt[node_id]['inputs']['filename_prefix'] = f'{output_prefix}_{name}'
    _add_mesh_pbr_maps(prompt, ['12', 0], output_prefix, checkpoint)
    return prompt


def build_prompt_mesh_basecolor_prompt(mesh_path, output_prefix, transfer, *,
                                      paint_steps=25, paint_view_size=512,
                                      paint_texture_size=2048, **settings):
    """Use FLUX's decoded image as the reference for the existing mesh-paint graph."""
    # Keep the original reference-generation controls, without executing Chord.
    reference_fields = {name for name, (node_id, _) in _PBR_PROMPT_FIELDS.items()
                        if node_id in {'1', '2', '3', '4', '6', '7', '8', '10'}}
    reference = build_prompt_material_prompt(
        output_prefix + '/reference', **{key: value for key, value in settings.items() if key in reference_fields})
    reference = _prune_graph(reference, ['10'])
    paint = build_mesh_basecolor_prompt(
        mesh_path, '', output_prefix + '/basecolor', transfer, steps=paint_steps,
        view_size=paint_view_size, texture_size=paint_texture_size, seed=int(settings.get('seed', 1024)),
        checkpoint=settings.get('checkpoint'))

    def renamed(graph, prefix):
        result = {}
        for node_id, node in graph.items():
            inputs = {}
            for name, value in node['inputs'].items():
                if (isinstance(value, list) and len(value) == 2
                        and isinstance(value[0], str) and value[0] in graph):
                    value = [prefix + value[0], value[1]]
                inputs[name] = value
            result[prefix + node_id] = dict(node, inputs=inputs)
        return result

    prompt = renamed(reference, 'ref_')
    prompt.update(renamed(paint, 'paint_'))
    # Feed the generated image directly, never apply that image to the target UV.
    del prompt['paint_2']
    prompt['reference_first'] = {
        'class_type': 'ImageFromBatch',
        'inputs': {'image': ['ref_9', 0], 'batch_index': 0, 'length': 1},
        '_meta': {'title': 'First prompt reference'},
    }
    prompt['paint_3']['inputs']['image'] = ['reference_first', 0]
    prompt['ref_10']['_meta']['title'] = 'Prompt Reference Image'
    prompt['ref_10']['_meta']['surface_reference'] = True
    prompt['paint_8']['_meta'] = {'title': 'Paint mesh views from prompt reference'}
    prompt['paint_13']['_meta']['title'] = 'Surface Albedo'
    return prompt


def material_prompt_defaults():
    """Read the supplied workflow's widget defaults, including its 64-bit seed."""
    prompt, _ = _load_prompt("PBR_PROMPT", None)
    defaults = {name: prompt[node_id]["inputs"][field]
                for name, (node_id, field) in _PBR_PROMPT_FIELDS.items()}
    defaults["seed"] = str(defaults["seed"])
    return defaults


def build_prompt_material_prompt(output_prefix, **settings):
    """Generate a texture with FLUX.2 and estimate its PBR maps with Chord."""
    prompt, _ = _load_prompt("PBR_PROMPT", None)
    for name, (node_id, field) in _PBR_PROMPT_FIELDS.items():
        if name in settings:
            prompt[node_id]["inputs"][field] = settings[name]
    seed = int(prompt["7"]["inputs"]["seed"])
    if not 0 <= seed <= 0xffffffffffffffff:
        raise ValueError("Seed must be between 0 and 18446744073709551615.")
    prompt["7"]["inputs"]["seed"] = seed
    if not str(prompt["4"]["inputs"]["text"]).strip():
        raise ValueError("Enter a material prompt.")
    for field in ("width", "height"):
        value = int(prompt["6"]["inputs"][field])
        if not 16 <= value <= 16384 or value % 16:
            raise ValueError("Generation width and height must be multiples of 16 (16–16384).")
        prompt["6"]["inputs"][field] = value
    _select_loader(prompt, str(prompt["1"]["inputs"]["unet_name"]),
                   str(prompt["3"]["inputs"]["clip_name"]))
    for node_id, field, setting in (("1", "weight_dtype", "weight_dtype"),
                                    ("3", "type", "clip_type"), ("3", "device", "clip_device")):
        if (node_id == "1" and prompt[node_id]["class_type"] == "UnetLoaderGGUF") or (
                field == "device" and prompt[node_id]["class_type"] == "CLIPLoaderGGUF"):
            continue
        prompt[node_id]["inputs"][field] = settings.get(setting, "flux2" if field == "type" else "default")
    for node_id, field in (("1", "unet_name"), ("3", "clip_name"),
                           ("8", "vae_name"), ("12", "ckpt_name")):
        prompt[node_id]["inputs"][field] = str(prompt[node_id]["inputs"][field]).replace("/", os.sep).replace("\\", os.sep)
    labels = {"10": "Generated Texture", "14": "Chord Base Color", "15": "Chord Normal",
              "16": "Chord Metallic", "17": "Chord Roughness", "19": "Chord Height"}
    for node_id, label in labels.items():
        suffix = str(prompt[node_id]["inputs"]["filename_prefix"]).strip().replace("\\", "/")
        if not suffix or os.path.isabs(suffix) or ".." in suffix.split("/"):
            raise ValueError("Output names must be non-empty paths inside this generation's output folder.")
        prompt[node_id]["inputs"]["filename_prefix"] = f"{output_prefix}/{suffix}"
        prompt[node_id]["_meta"]["title"] = label
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
    use_reference_alpha = reference_is_render or not settings.get("remove_reference_background", True)
    for _, node in _nodes(prompt, "UltraTexPrep"):
        node["inputs"].update(render_size=int(settings.get("render_size", 4096)), atlas_size=int(settings.get("atlas_size", node["inputs"].get("atlas_size", 4096))), uv_mode=settings.get("uv_mode", "comfy_gpu"), reference_alignment=settings.get("reference_alignment", "fit_front_silhouette"))
        if not use_reference:
            node["inputs"].pop("reference_image", None)
            node["inputs"].pop("reference_mask", None)
        elif use_reference_alpha:
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
            elif use_reference_alpha:
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
    bakes = [(key, node) for key, node in prompt.items()
             if node['class_type'] in {'UltraTexBake', 'UTXBakeTextureV26'}]
    if len(bakes) != 1:
        raise ValueError('Expected one final UV bake for normal generation.')
    output_ids.append(_add_detail_normal(prompt, [bakes[0][0], 1], output_prefix))
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
