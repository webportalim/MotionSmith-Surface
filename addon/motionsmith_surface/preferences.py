"""MotionSmith Surface - Addon Preferences."""

import os
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, EnumProperty
from bpy.types import AddonPreferences, Operator

ADDON_ID = "motionsmith_surface"
_previews = None


def get_icon_id(name="icon"):
    return _previews[name].icon_id if _previews and name in _previews else 0


def get_comfyui_dir(context=None):
    prefs = get_preferences(context)
    if prefs and prefs.comfyui_dir:
        return os.path.abspath(bpy.path.abspath(prefs.comfyui_dir))
    return os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "comfyui"))


def get_preferences(context=None) -> AddonPreferences:
    """Safely get addon preferences."""
    if context is None:
        context = bpy.context
    prefs = context.preferences.addons.get(ADDON_ID)
    if prefs:
        return prefs.preferences
    # Fallback to search by package
    pkg = __package__ or ADDON_ID
    prefs = context.preferences.addons.get(pkg)
    if prefs:
        return prefs.preferences
    return None


def _on_port_changed(self, context):
    try:
        if "127.0.0.1" in self.server_url or "localhost" in self.server_url:
            self.server_url = f"http://127.0.0.1:{self.server_port}"
    except Exception:
        pass


def _on_backend_directory_changed(self, context):
    if self.comfyui_dir:
        python = os.path.join(bpy.path.abspath(self.comfyui_dir), ".venv", "Scripts", "python.exe")
        if os.path.isfile(python):
            self.python_executable = python


class MOTIONSMITH_SURFACE_OT_install(Operator):
    bl_idname = "motionsmith_surface.install"
    bl_label = "Install"
    bl_description = "Open the bundled Windows installer to download the backend and models"

    def execute(self, context):
        if os.name != 'nt':
            self.report({'ERROR'}, "The bundled installer requires Windows")
            return {'CANCELLED'}
        installer = os.path.join(os.path.dirname(__file__), "install_motionsmith_surface.bat")
        if not os.path.isfile(installer):
            self.report({'ERROR'}, "Bundled installer is missing; reinstall the add-on")
            return {'CANCELLED'}
        try:
            os.startfile(installer, "open", cwd=os.path.dirname(installer), show_cmd=1)
        except OSError as exc:
            self.report({'ERROR'}, f"Could not open installer: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, "Installer opened. After setup, set the displayed ComfyUI path in Backend.")
        return {'FINISHED'}


class MotionSmithSurfacePreferences(AddonPreferences):
    bl_idname = ADDON_ID

    preferences_page: EnumProperty(
        name="Preferences",
        items=[("OVERVIEW", "Overview", "Features and getting started"),
               ("BACKEND", "Backend", "Configure your local ComfyUI installation"),
               ("REQUIREMENTS", "Requirements", "Supported environment and model files"),
               ("MODELS", "Models", "Check installed model files")],
        default="OVERVIEW",
        options={'SKIP_SAVE'},
    )

    server_url: StringProperty(
        name="ComfyUI Server URL",
        description="Address of the ComfyUI API server",
        default="http://127.0.0.1:8188",
    )

    comfyui_dir: StringProperty(
        name="ComfyUI Directory",
        description="Path to minimal ComfyUI directory for MotionSmith Surface",
        subtype="DIR_PATH",
        update=_on_backend_directory_changed,
        default=os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "comfyui")),
    )

    python_executable: StringProperty(
        name="Python Executable",
        description="Path to ComfyUI Python environment",
        subtype="FILE_PATH",
        default=os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "comfyui", ".venv", "Scripts", "python.exe")),
    )

    server_port: IntProperty(
        name="Server Port",
        description="Port for the local ComfyUI server",
        default=8188,
        min=1024,
        max=65535,
        update=_on_port_changed,
    )

    show_console: BoolProperty(
        name="Show Server Console",
        description="Open ComfyUI in a dedicated console window so you can monitor server output",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        logo = get_icon_id("logo")
        if logo:
            row = layout.row()
            row.alignment = 'LEFT'
            row.template_icon(icon_value=logo, scale=6.0)
        row = layout.row()
        row.alignment = 'LEFT'
        row.label(text="MotionSmith Surface", icon_value=get_icon_id())
        layout.separator()

        box = layout.box()
        box.label(text="Backend & Models Setup", icon="IMPORT")
        row = box.row()
        row.enabled = os.name == 'nt'
        row.operator("motionsmith_surface.install", text="Install", icon="IMPORT")
        box.label(text="Opens setup in a separate window. Downloads the backend and models automatically.")

        layout.row().prop(self, "preferences_page", expand=True)
        layout.separator()
        if self.preferences_page == "MODELS":
            from . import model_catalog
            layout.label(text="Use Install above to set up the backend and models.", icon="INFO")
            layout.label(text="Model status uses the ComfyUI directory configured in Backend.")
            models = os.path.join(bpy.path.abspath(self.comfyui_dir), "models")
            for label, relative, _url in model_catalog.MODEL_DOWNLOADS:
                box = layout.box()
                path = os.path.join(models, *relative.split("/"))
                found = os.path.isfile(path)
                if relative == "checkpoints/SD/chord_v1.safetensors":
                    found = found or os.path.isfile(os.path.join(models, "checkpoints", "chord_v1.safetensors"))
                row = box.row(align=True)
                row.label(text=label, icon='CHECKMARK' if found else 'IMPORT')
                row.label(text="Installed" if found else "Missing")
            layout.label(text="Chord: Research-Only license. Model publishers may require license acceptance.", icon="INFO")
            layout.operator("motionsmith_surface.refresh_models", text="Refresh Installed Models", icon='FILE_REFRESH')
            return
        if self.preferences_page == "OVERVIEW":
            box = layout.box()
            box.label(text="AI Texturing & PBR Materials for Blender", icon="MATERIAL")
            box.label(text="Texture meshes with UltraTex, or turn an image into PBR maps with Chord.")
            box.label(text="Runs on your local ComfyUI backend. Generated maps are packed into the blend file.")
            box = layout.box()
            box.label(text="Get Started", icon="PLAY")
            box.label(text="1. Set your ComfyUI directory and Python executable in Backend.")
            box.label(text="2. Open the Surface sidebar and start the server.")
            box.label(text="3. Choose Texture or PBR Material, provide your inputs, and Generate.")
            box = layout.box()
            box.label(text="Texture", icon="MESH_DATA")
            box.label(text="Image and optional text guidance, multiple views, UV baking and material assignment.")
            box.label(text="PBR Material", icon="SHADING_TEXTURE")
            box.label(text="Base Color, Normal, Roughness, Metallic and Height from one image.")
            box.label(text="Select a UV-mapped mesh to apply the material to its active slot.")
            return

        if self.preferences_page == "REQUIREMENTS":
            box = layout.box()
            box.label(text="Environment", icon="SYSTEM")
            box.label(text="Windows 64-bit | Blender 5.0+ (tested with Blender 5.2)")
            box.label(text="NVIDIA GPU with a CUDA-compatible PyTorch build for AI generation.")
            box.label(text="VRAM usage depends on the model, resolution and workflow.")
            box = layout.box()
            box.label(text="Tested Backend", icon="CHECKMARK")
            box.label(text="ComfyUI 0.27.0 | Frontend 1.45.20 | Python 3.12.10")
            box.label(text="PyTorch 2.8.0 + CUDA 12.8 | torchvision 0.23.0")
            box.label(text="UltraTex: trimesh, xatlas, moderngl, glcontext | Quantized models: gguf")
            box.label(text="Chord: diffusers, torchvision, omegaconf, imageio")
            box.label(text="Background removal: BiRefNet | Blender live progress: websocket-client")
            box = layout.box()
            box.label(text="Required Model Files", icon="FILE_FOLDER")
            for text in (
                "Texture: FLUX.2 Klein BASE diffusion model (GGUF supported)",
                "Text encoder: qwen_3_8b_fp8mixed.safetensors",
                "VAE: flux2-vae.safetensors",
                "Albedo / MR LoRAs: ultratex_flux2.safetensors / ultratex_flux2_mr.safetensors",
                "Decoder: ultratex_flux2_decoder.pt | Background removal: birefnet.safetensors",
                "PBR Material: chord_v1.safetensors (checkpoints folder)",
            ):
                box.label(text=text)
            box.label(text="The runtime currently uses installed models; it does not download missing files.")
            box.label(text="Chord is supplied under the Ubisoft Machine Learning Research-Only license.", icon="INFO")
            return

        box = layout.box()
        box.label(text="Backend Server Configuration", icon="NETWORK_DRIVE")
        box.prop(self, "server_url")
        box.prop(self, "server_port")
        box.prop(self, "show_console")
        box.prop(self, "comfyui_dir")
        box.prop(self, "python_executable")
        box = layout.box()
        box.label(text="Local Installation", icon="FILE_FOLDER")
        directory = os.path.abspath(bpy.path.abspath(self.comfyui_dir)) if self.comfyui_dir else ""
        python_path = bpy.path.abspath(self.python_executable) if self.python_executable else ""
        checks = (
            ("ComfyUI main.py", bool(directory and os.path.isfile(os.path.join(directory, "main.py")))),
            ("Python executable", bool(python_path and os.path.isfile(python_path))),
            ("Models directory", bool(directory and os.path.isdir(os.path.join(directory, "models")))),
        )
        for label, found in checks:
            box.label(text=f"{label}: {'Found' if found else 'Not found'}", icon='CHECKMARK' if found else 'ERROR')
        if directory and os.path.isdir(directory):
            box.operator("wm.path_open", text="Open ComfyUI Folder", icon='FILE_FOLDER').filepath = directory


def register():
    global _previews
    from bpy.utils import previews
    _previews = previews.new()
    directory = os.path.dirname(__file__)
    _previews.load("icon", os.path.join(directory, "icon-256.png"), 'IMAGE')
    _previews.load("logo", os.path.join(directory, "icon.png"), 'IMAGE')
    bpy.utils.register_class(MOTIONSMITH_SURFACE_OT_install)
    bpy.utils.register_class(MotionSmithSurfacePreferences)


def unregister():
    global _previews
    bpy.utils.unregister_class(MotionSmithSurfacePreferences)
    bpy.utils.unregister_class(MOTIONSMITH_SURFACE_OT_install)
    if _previews is not None:
        from bpy.utils import previews
        previews.remove(_previews)
        _previews = None
