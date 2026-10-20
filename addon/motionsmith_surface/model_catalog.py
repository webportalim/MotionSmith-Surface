"""MotionSmith Surface - Model Catalog & Discovery."""

import os

_CACHE: dict[str, list[tuple[str, str, str]]] = {}

# Original publishers or model-conversion publishers; weights are never bundled.
MODEL_DOWNLOADS = (
    ("Texture - BASE Diffusion (GGUF Q4_0)", "diffusion_models/flux-2-klein-base-9b-Q4_0.gguf",
     "https://huggingface.co/unsloth/FLUX.2-klein-base-9B-GGUF/resolve/main/flux-2-klein-base-9b-Q4_0.gguf?download=true"),
    ("Texture - Text Encoder", "text_encoders/qwen_3_8b_fp8mixed.safetensors",
     "https://huggingface.co/Comfy-Org/flux2-klein-9B/resolve/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors?download=true"),
    ("Texture - VAE", "vae/flux2-vae.safetensors",
     "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors?download=true"),
    ("Texture - Albedo LoRA", "loras/ultratex_flux2.safetensors",
     "https://www.modelscope.ai/models/Yibo-Zhang/UltraTex/resolve/master/flux2/lora/dit_lora.safetensors?view=false"),
    ("Texture - Metallic / Roughness LoRA", "loras/ultratex_flux2_mr.safetensors",
     "https://www.modelscope.ai/models/Yibo-Zhang/UltraTex/resolve/master/flux2_mr/lora/dit_lora.safetensors?view=false"),
    ("Texture - Decoder", "ultratex/ultratex_flux2_decoder.pt",
     "https://www.modelscope.ai/models/Yibo-Zhang/UltraTex/resolve/master/flux2/decoder.pt?view=false"),
    ("Texture - Background Removal", "background_removal/birefnet.safetensors",
     "https://huggingface.co/Comfy-Org/BiRefNet/resolve/main/background_removal/birefnet.safetensors?download=true"),
    ("PBR Material - Chord", "checkpoints/SD/chord_v1.safetensors",
     "https://huggingface.co/Ubisoft/ubisoft-laforge-chord/resolve/main/chord_v1.safetensors?download=true"),
)


def get_models_dir(context=None) -> str:
    """Resolve the models root directory."""
    from . import preferences

    prefs = preferences.get_preferences(context)
    if prefs and prefs.comfyui_dir:
        configured_models = os.path.join(os.path.abspath(prefs.comfyui_dir), "models")
        if os.path.isdir(configured_models):
            return configured_models
        return ""
    addon_comfy_models = os.path.abspath(
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "comfyui", "models")
    )
    if os.path.isdir(addon_comfy_models):
        return addon_comfy_models
    return ""


def scan_category(category: str, default_item: str = "", context=None) -> list[tuple[str, str, str]]:
    """Scan subfolder for model files and return EnumProperty tuples."""
    models_dir = get_models_dir(context)
    cache_key = f"{models_dir}|{category}|{default_item}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    found_files = []

    if models_dir:
        cat_dir = os.path.join(models_dir, category)
        if os.path.isdir(cat_dir):
            for root, _, files in os.walk(cat_dir):
                for f in sorted(files):
                    if f.lower().endswith(('.safetensors', '.gguf', '.pt', '.ckpt', '.bin')):
                        rel = os.path.relpath(os.path.join(root, f), cat_dir).replace("\\", "/")
                        found_files.append(rel)

    # Bring default item to the top of list
    if default_item:
        norm_default = default_item.replace("\\", "/")
        matching = [x for x in found_files if x.lower() == norm_default.lower() or os.path.basename(x).lower() == os.path.basename(norm_default).lower()]
        if matching:
            found_files.remove(matching[0])
            found_files.insert(0, matching[0])

    enum_items = []
    for m in found_files:
        name = os.path.basename(m)
        enum_items.append((m, name, m))

    if not enum_items:
        enum_items = [("__MISSING__", "No installed models", f"No model files found in {category}")]

    _CACHE[cache_key] = enum_items
    return enum_items


def refresh_catalog():
    """Clear cached model lists to rescan."""
    _CACHE.clear()


# Callback functions for Blender EnumProperties
def get_diffusion_models(self, context):
    return scan_category("diffusion_models", "flux-2-klein-base-9b-Q4_0.gguf", context)


def get_text_encoders(self, context):
    return scan_category("text_encoders", "qwen_3_8b_fp8mixed.safetensors", context)


def get_vae_models(self, context):
    return scan_category("vae", "flux2-vae.safetensors", context)


def get_decoder_models(self, context):
    return scan_category("ultratex", "ultratex_flux2_decoder.pt", context)


def get_lora_albedo_models(self, context):
    return scan_category("loras", "ultratex_flux2.safetensors", context)


def get_lora_mr_models(self, context):
    return scan_category("loras", "ultratex_flux2_mr.safetensors", context)


def get_bg_removal_models(self, context):
    return scan_category("background_removal", "birefnet.safetensors", context)


def get_pbr_diffusion_models(self, context):
    return scan_category("diffusion_models", "flux-2-klein-9b-fp8.safetensors", context)


def get_pbr_vae_models(self, context):
    return scan_category("vae", "ae_flux2.safetensors", context)


def get_pbr_checkpoints(self, context):
    return scan_category("checkpoints", "SD/chord_v1.safetensors", context)
