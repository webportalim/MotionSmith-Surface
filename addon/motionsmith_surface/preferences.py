"""MotionSmith Surface - Addon Preferences."""

import os
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, EnumProperty
from bpy.types import AddonPreferences, Operator

ADDON_ID = __package__ or "motionsmith_surface"
DOCS_URL = "https://huggingface.co/Serqan/MotionSmith-Runtime/blob/main/blender/MotionSmith-Surface/README.md"
WEBSITE_URL = "https://motionsmithai.blogspot.com/p/motionsmith-surface.html"
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

    # 1. Package lookup (standard for Blender 4.2+ extensions)
    pkg = __package__
    if pkg and pkg in context.preferences.addons:
        addon = context.preferences.addons[pkg]
        if addon and addon.preferences:
            return addon.preferences

    # 2. Resolved ADDON_ID lookup
    if ADDON_ID in context.preferences.addons:
        addon = context.preferences.addons[ADDON_ID]
        if addon and addon.preferences:
            return addon.preferences

    # 3. Base ID lookup (legacy add-on mode)
    if "motionsmith_surface" in context.preferences.addons:
        addon = context.preferences.addons["motionsmith_surface"]
        if addon and addon.preferences:
            return addon.preferences

    # 4. Fallback search across installed add-ons
    for key, addon in context.preferences.addons.items():
        if key == "motionsmith_surface" or key.endswith(".motionsmith_surface"):
            if addon and addon.preferences:
                return addon.preferences
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

        # Header Box with Title & Tagline
        header_box = layout.box()
        title_row = header_box.row(align=True)
        title_row.alignment = 'LEFT'

        icon_id = get_icon_id("icon") or get_icon_id("logo")
        if icon_id:
            title_row.label(text="MotionSmith Surface", icon_value=icon_id)
        else:
            title_row.label(text="MotionSmith Surface", icon="MATERIAL")

        sub_col = header_box.column(align=True)
        sub_col.scale_y = 0.85
        sub_col.label(text="AI PBR Texturing and Material Generation for Blender")

        # Quick Links / Action Bar
        action_row = header_box.row(align=True)
        action_row.scale_y = 1.15

        op_docs = action_row.operator("wm.url_open", text="Documentation (README)", icon="HELP")
        op_docs.url = DOCS_URL

        op_web = action_row.operator("wm.url_open", text="Official Website", icon="URL")
        op_web.url = WEBSITE_URL

        op_install = action_row.operator("motionsmith_surface.install", text="Install Backend & Models", icon="IMPORT")
        if os.name != 'nt':
            op_install.enabled = False

        layout.separator(factor=0.5)

        # Tab Navigation Bar
        tab_row = layout.row(align=True)
        tab_row.prop(self, "preferences_page", expand=True)
        layout.separator()

        # Tab 1: OVERVIEW
        if self.preferences_page == "OVERVIEW":
            feat_box = layout.box()
            feat_box.label(text="Features & Capabilities", icon="SHADING_RENDERED")
            feat_col = feat_box.column(align=True)
            feat_col.label(text="• UltraTex 3D Texturing: AI mesh texturing with multi-view projection and seamless UV transfer.")
            feat_col.label(text="• Chord PBR Generation: Generate Base Color, Normal, Roughness, Metallic & Height maps from single images.")
            feat_col.label(text="• Local ComfyUI Backend: Full inference runs locally on your NVIDIA GPU with live progress feedback.")
            feat_col.label(text="• Auto Packing: All generated texture maps and materials are packed directly into your Blender scene.")

            steps_box = layout.box()
            steps_box.label(text="Getting Started", icon="PLAY")
            steps_col = steps_box.column(align=True)
            steps_col.label(text="1. Backend Setup: Set your ComfyUI directory and Python path in the 'Backend' tab, or click Install.")
            steps_col.label(text="2. Sidebar Access: In the 3D Viewport, press [N] to open the sidebar and navigate to the 'Surface' tab.")
            steps_col.label(text="3. Start Server: Click 'Start ComfyUI Server' to boot the backend service.")
            steps_col.label(text="4. Generate: Select your mesh, choose Texture or PBR Material mode, set inputs, and click Generate.")

            links_box = layout.box()
            links_box.label(text="Documentation & Online Resources", icon="WORLD")
            links_box.label(text="Access full workflow guides, model checkpoints, tutorials, and project updates:")
            btn_row = links_box.row(align=True)
            btn_row.scale_y = 1.15
            b_docs = btn_row.operator("wm.url_open", text="Hugging Face Documentation & Runtime", icon="HELP")
            b_docs.url = DOCS_URL
            b_site = btn_row.operator("wm.url_open", text="Official Website & Blog", icon="URL")
            b_site.url = WEBSITE_URL

            setup_box = layout.box()
            setup_box.label(text="Automated Windows Setup", icon="IMPORT")
            setup_box.label(text="Downloads the minimal ComfyUI backend and required AI models into your environment.")
            s_row = setup_box.row()
            s_row.scale_y = 1.1
            s_row.enabled = os.name == 'nt'
            s_row.operator("motionsmith_surface.install", text="Launch Setup Installer", icon="IMPORT")
            return

        # Tab 2: BACKEND
        if self.preferences_page == "BACKEND":
            info_box = layout.box()
            info_box.label(text="External / Standalone ComfyUI Notice", icon="INFO")
            info_col = info_box.column(align=True)
            info_col.scale_y = 0.85
            info_col.label(text="• If ComfyUI is already running externally, you do NOT need 'Start Server'.")
            info_col.label(text="• Simply make sure Server URL matches (default: http://127.0.0.1:8188) and press Refresh in the sidebar.")
            info_col.label(text="• 'Start Server' and ComfyUI Directory below are only required if launching locally from Blender.")

            srv_box = layout.box()
            srv_box.label(text="ComfyUI Server Settings", icon="NETWORK_DRIVE")
            srv_box.prop(self, "server_url")
            srv_box.prop(self, "server_port")
            srv_box.prop(self, "show_console")
            srv_box.prop(self, "comfyui_dir")
            srv_box.prop(self, "python_executable")

            local_box = layout.box()
            local_box.label(text="Installation Verification", icon="FILE_FOLDER")
            directory = os.path.abspath(bpy.path.abspath(self.comfyui_dir)) if self.comfyui_dir else ""
            python_path = bpy.path.abspath(self.python_executable) if self.python_executable else ""
            checks = (
                ("ComfyUI main.py", bool(directory and os.path.isfile(os.path.join(directory, "main.py")))),
                ("Python Executable", bool(python_path and os.path.isfile(python_path))),
                ("Models Directory", bool(directory and os.path.isdir(os.path.join(directory, "models")))),
            )
            for label, found in checks:
                row = local_box.row()
                row.label(text=label, icon='CHECKMARK' if found else 'CANCEL')
                row.label(text="Found" if found else "Not found")

            local_box.label(text="Note: Local files are only needed if starting ComfyUI directly from Blender.", icon="INFO")

            act_row = local_box.row(align=True)
            if directory and os.path.isdir(directory):
                act_row.operator("wm.path_open", text="Open ComfyUI Folder", icon='FILE_FOLDER').filepath = directory
            if os.name == 'nt':
                act_row.operator("motionsmith_surface.install", text="Install / Setup Backend", icon='IMPORT')
            return

        # Tab 3: REQUIREMENTS
        if self.preferences_page == "REQUIREMENTS":
            env_box = layout.box()
            env_box.label(text="System Requirements", icon="SYSTEM")
            env_col = env_box.column(align=True)
            env_col.label(text="• OS: Windows 64-bit (Windows 10 / 11)")
            env_col.label(text="• Blender: 5.0+ (Tested & verified on Blender 5.2)")
            env_col.label(text="• GPU: NVIDIA GeForce RTX with CUDA support (8GB+ VRAM for GGUF/SD, 12GB+ for full FLUX)")

            stack_box = layout.box()
            stack_box.label(text="Tested Backend Environment", icon="CHECKMARK")
            stack_col = stack_box.column(align=True)
            stack_col.label(text="• ComfyUI 0.27.0 | Frontend 1.45.20 | Python 3.12.10 | PyTorch 2.8.0 + CUDA 12.8")
            stack_col.label(text="• UltraTex modules: trimesh, xatlas, moderngl, glcontext, gguf")
            stack_col.label(text="• Chord PBR modules: diffusers, torchvision, omegaconf, imageio")
            stack_col.label(text="• Background removal: BiRefNet | Live progress: websocket-client")

            models_box = layout.box()
            models_box.label(text="Required Model Weights", icon="FILE_FOLDER")
            m_col = models_box.column(align=True)
            m_col.label(text="• FLUX.2 Klein Base diffusion model (or GGUF Q4_0 quantized)")
            m_col.label(text="• Qwen 3.8B FP8 mixed text encoder (qwen_3_8b_fp8mixed.safetensors)")
            m_col.label(text="• Flux2 VAE (flux2-vae.safetensors)")
            m_col.label(text="• UltraTex LoRAs (ultratex_flux2.safetensors & ultratex_flux2_mr.safetensors)")
            m_col.label(text="• UltraTex Decoder (ultratex_flux2_decoder.pt)")
            m_col.label(text="• Background removal (birefnet.safetensors)")
            m_col.label(text="• Chord PBR checkpoint (chord_v1.safetensors in checkpoints folder)")

            r_row = models_box.row()
            r_row.operator("wm.url_open", text="Read Full Model Documentation on Hugging Face", icon="HELP").url = DOCS_URL
            return

        # Tab 4: MODELS
        if self.preferences_page == "MODELS":
            from . import model_catalog

            info_box = layout.box()
            info_box.label(text="Installed Model Files Audit", icon="ASSET_MANAGER")
            info_col = info_box.column(align=True)
            info_col.label(text="Verifies presence of required AI weights in configured ComfyUI models directory.")
            info_col.label(text="Missing models can be downloaded automatically via Install or manually from Hugging Face.")

            models_dir = os.path.join(bpy.path.abspath(self.comfyui_dir), "models") if self.comfyui_dir else ""
            has_dir = bool(models_dir and os.path.isdir(models_dir))

            if not has_dir:
                warn_box = layout.box()
                warn_box.label(text="ComfyUI models folder not found. Please set valid ComfyUI directory in Backend.", icon="ERROR")

            for label, relative, _url in model_catalog.MODEL_DOWNLOADS:
                box = layout.box()
                path = os.path.join(models_dir, *relative.split("/")) if has_dir else ""
                found = bool(path and os.path.isfile(path))
                if not found and relative == "checkpoints/SD/chord_v1.safetensors" and has_dir:
                    found = os.path.isfile(os.path.join(models_dir, "checkpoints", "chord_v1.safetensors"))

                row = box.row(align=True)
                row.label(text=label, icon='CHECKMARK' if found else 'CANCEL')
                row.label(text="Installed" if found else "Missing")
                if not found:
                    dl_op = row.operator("wm.url_open", text="Download", icon="IMPORT")
                    dl_op.url = _url

            layout.separator()
            act_row = layout.row(align=True)
            act_row.operator("motionsmith_surface.refresh_models", text="Refresh Installed Models", icon='FILE_REFRESH')
            hf_op = act_row.operator("wm.url_open", text="Documentation & Downloads (Hugging Face)", icon='HELP')
            hf_op.url = DOCS_URL
            if os.name == 'nt':
                act_row.operator("motionsmith_surface.install", text="Install All Models", icon='IMPORT')
            return


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
