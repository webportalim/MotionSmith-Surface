"""MotionSmith Surface - 3D View Sidebar UI Panels and Scene Properties."""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Panel, PropertyGroup

from . import model_catalog
from . import preferences
from . import camera_utils


DEFAULT_SURFACE_PROMPT = (
    "Use the reference image as the primary guide. Preserve its colors, patterns, "
    "material appearance and surface details. Generate consistent PBR textures "
    "across the mesh without introducing a different material style."
)


def _on_workflow_changed(self, context):
    self.camera_setup_mode = camera_utils.get_capture_mode(self)


def _on_style_preset_changed(self, context):
    presets = {
        "GOLD": "A realistic high quality photorealistic polished gold PBR material, shiny reflective surface, subtle surface imperfections, 8k texture",
        "SILVER": "A realistic high quality polished chrome silver metal PBR material, mirror reflections, sharp specular highlights, 8k texture",
        "BRONZE": "A realistic antique bronze copper PBR material, subtle aged patina, warm metallic highlights, detailed 8k texture",
        "MARBLE": "A realistic polished white Carrara marble PBR material, elegant grey veining, smooth glossy surface, 8k texture",
        "WOOD": "A realistic polished rich dark oak wood PBR material, natural grain pattern, satin clear coat, 8k texture",
        "LEATHER": "A realistic weathered dark brown leather PBR material, fine grain texture, soft creases, detailed 8k texture",
    }
    if self.style_preset in presets:
        self.positive_prompt = presets[self.style_preset]
    elif self.style_preset == "CUSTOM" and self.positive_prompt in presets.values():
        self.positive_prompt = DEFAULT_SURFACE_PROMPT


def _on_view_resolution_changed(self, context):
    try:
        res = int(self.view_resolution)
        context.scene.render.resolution_x = res
        context.scene.render.resolution_y = res
        context.scene.render.resolution_percentage = 100
        context.scene.render.pixel_aspect_x = 1.0
        context.scene.render.pixel_aspect_y = 1.0
    except Exception:
        pass


class MotionSmithSurfaceSceneProperties(PropertyGroup):
    generation_progress: FloatProperty(default=-1.0, min=-1.0, max=1.0, options={'HIDDEN', 'SKIP_SAVE'})
    generation_remaining: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    page: EnumProperty(
        name="Page",
        items=[("TEXTURE", "Texture", "UltraTex mesh texturing"),
               ("PBR_MATERIAL", "PBR Material", "Convert an image into Chord PBR maps")],
        default="TEXTURE",
    )
    pbr_image: StringProperty(name="Image", subtype="FILE_PATH", default="")
    is_generating: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    server_online: BoolProperty(
        name="Server Online",
        description="Whether the local ComfyUI server is reachable",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    server_status: EnumProperty(
        name="Server Status",
        description="Lifecycle status of local ComfyUI server",
        items=[
            ("OFFLINE", "Offline", "Server is not running"),
            ("STARTING", "Starting...", "Server is booting up"),
            ("ONLINE", "Online", "Server is listening and ready"),
            ("STOPPING", "Stopping...", "Server is shutting down"),
        ],
        default="OFFLINE",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    generation_status: StringProperty(
        name="Status",
        description="Current execution or generation status",
        default="Ready",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    last_prompt_id: StringProperty(
        name="Last Prompt ID",
        default="",
        options={'HIDDEN'},
    )

    last_target_name: StringProperty(
        name="Last Target Name",
        default="",
        options={'HIDDEN'},
    )

    input_mode: EnumProperty(
        name="Input Mode",
        description="Choose the material guidance supplied to the automatic workflow",
        items=[
            ("PROMPT", "Prompt Only", "Use text and mesh geometry; no image or camera appearance reference"),
            ("IMAGE", "Image Only", "Use a reference image or front-camera capture; no positive/negative text guidance"),
            ("BOTH", "Prompt + Image", "Combine text with a reference image or front-camera capture"),
        ],
        default="BOTH",
    )

    # --- TEXT GUIDANCE & PROMPTS ---
    positive_prompt: StringProperty(
        name="Positive Prompt",
        description="Detailed description of desired PBR surface material, color, finish, and details",
        default=DEFAULT_SURFACE_PROMPT,
        maxlen=2048,
    )

    negative_prompt: StringProperty(
        name="Negative Prompt",
        description="Negative guidance to prevent artifacts, cartoon styling, low quality, or blur",
        default="blurry, low quality, distorted, cartoon, flat, bad lighting, noisy, watermark",
        maxlen=2048,
    )

    # --- MODEL SELECTION PROPERTIES ---
    unet_model: EnumProperty(
        name="Diffusion (UNET)",
        description="FLUX.2 Klein base diffusion model",
        items=model_catalog.get_diffusion_models,
    )

    clip_model: EnumProperty(
        name="Text Encoder (CLIP)",
        description="Text encoder model (Qwen3 / CLIP)",
        items=model_catalog.get_text_encoders,
    )

    vae_model: EnumProperty(
        name="VAE",
        description="FLUX.2 VAE model",
        items=model_catalog.get_vae_models,
    )

    decoder_model: EnumProperty(
        name="Decoder",
        description="UltraTex foreground VAE decoder (.pt)",
        items=model_catalog.get_decoder_models,
    )

    lora_albedo_model: EnumProperty(
        name="Albedo LoRA",
        description="UltraTex albedo LoRA",
        items=model_catalog.get_lora_albedo_models,
    )

    lora_mr_model: EnumProperty(
        name="MR LoRA",
        description="UltraTex metallic-roughness LoRA",
        items=model_catalog.get_lora_mr_models,
    )

    bg_removal_model: EnumProperty(
        name="BG Removal",
        description="Background removal model (BiRefNet)",
        items=model_catalog.get_bg_removal_models,
    )

    # --- CAMERA SETUP IN BLENDER ---
    camera_setup_mode: EnumProperty(
        name="Camera Setup",
        description="Select camera setup in Blender",
        items=[
            ("SINGLE", "1 Camera (Front View)", "Creates 1 calibrated front camera framing the mesh. Renders reference image for ComfyUI LoadImage"),
            ("MULTI", "6 Cameras (Rig Views)", "Creates 6 calibrated cameras (Front, Left, Back, Right, Top, Bottom) around the mesh"),
            ("MANUAL_10", "10 Cameras (Manual Views)", "Six canonical cameras and four diagonals used as workflow image inputs"),
        ],
        default="SINGLE",
    )

    # --- TEXTURE GENERATION QUALITY / WORKFLOW ---
    texture_quality: EnumProperty(
        name="Workflow",
        description="Select a workflow from ComfyUI's PixelArtistry folder",
        items=[
            ("10_VIEWS", "10 Views - 2 Pass (Advanced Seamless)", "Official UltraTex workflow: 1 camera reference -> Pass 1 (6 views) + Pass 2 (4 diagonal views at 45°) -> Seamless 4K PBR"),
            ("6_VIEWS", "6 Views - 1 Pass (Standard Fast)", "Standard workflow: 1 camera reference -> Pass 1 (6 views) -> Standard PBR"),
            ("MANUAL_10_VIEWS", "10 Views - Manual Camera Inputs", "UltraTex_Manual_10_Views_PBR.json: capture all ten camera views and use them as workflow inputs"),
            ("LOW_VRAM_GGUF", "Low VRAM - GGUF", "UltraTex - 3 Low VRAM GGUF.json: modular generation and PBR bake with installed GGUF models"),
        ],
        default="10_VIEWS",
        update=_on_workflow_changed,
    )

    # Legacy alias for camera_mode
    camera_mode: EnumProperty(
        name="Camera Mode (Legacy)",
        items=[
            ("SINGLE", "Single", "Single camera"),
            ("MULTI", "Multi", "Multi camera"),
        ],
        default="SINGLE",
    )

    multiview_denoise: FloatProperty(
        name="Pass 2 Denoise",
        description="Denoise strength for 45° diagonal angle refinement (default 0.6: lower keeps more of pass 1)",
        default=0.6,
        min=0.0,
        max=1.0,
        step=5,
    )

    # --- MATERIAL STYLE & REFERENCE ---
    style_preset: EnumProperty(
        name="Material Style",
        description="Select material preset or use custom prompt",
        items=[
            ("GOLD", "Gold Metallic", "Rich polished reflective gold finish"),
            ("SILVER", "Silver / Chrome", "Polished metallic chrome/silver surface"),
            ("BRONZE", "Bronze / Copper", "Burnished warm copper/bronze surface"),
            ("MARBLE", "White Marble", "Polished Carrara marble with fine grey veins"),
            ("WOOD", "Oak Wood", "Polished rich dark oak wood grain"),
            ("LEATHER", "Leather", "Weathered brown leather texture"),
            ("CUSTOM", "No Preset / Custom", "Use your own prompt or leave it empty for image guidance only"),
        ],
        default="CUSTOM",
        update=_on_style_preset_changed,
    )

    custom_reference_image: StringProperty(
        name="Reference Image",
        description="Path to reference image file on disk",
        subtype="FILE_PATH",
        default="",
    )

    # --- MANUAL 10 VIEWS INPUT OPTIONS ---
    manual_source: EnumProperty(
        name="10 Views Source",
        description="Choose how 10 camera views are supplied for the manual workflow",
        items=[
            ("CAMERAS", "10 Blender Cameras (Auto)", "Render 10 calibrated views around the target mesh in Blender"),
            ("FOLDER", "Image Folder (10 Views)", "Folder containing 10 view photos (named front, left, back, right, top, bottom, front_left, back_left, back_right, front_right)"),
            ("FILES", "10 Individual Photos", "Select 10 individual photo files manually"),
        ],
        default="CAMERAS",
    )
    manual_images_dir: StringProperty(
        name="10 Views Folder",
        description="Folder containing 10 view images",
        subtype="DIR_PATH",
        default="",
    )
    manual_image_0_front: StringProperty(name="Front 0° (Ön)", subtype="FILE_PATH", default="")
    manual_image_1_left: StringProperty(name="Left 270° (Sol)", subtype="FILE_PATH", default="")
    manual_image_2_back: StringProperty(name="Back 180° (Arka)", subtype="FILE_PATH", default="")
    manual_image_3_right: StringProperty(name="Right 90° (Sağ)", subtype="FILE_PATH", default="")
    manual_image_4_top: StringProperty(name="Top (Üstten)", subtype="FILE_PATH", default="")
    manual_image_5_bottom: StringProperty(name="Bottom (Alttan)", subtype="FILE_PATH", default="")
    manual_image_6_front_left: StringProperty(name="Front-Left 315° (Ön-Sol)", subtype="FILE_PATH", default="")
    manual_image_7_back_left: StringProperty(name="Back-Left 225° (Arka-Sol)", subtype="FILE_PATH", default="")
    manual_image_8_back_right: StringProperty(name="Back-Right 135° (Arka-Sağ)", subtype="FILE_PATH", default="")
    manual_image_9_front_right: StringProperty(name="Front-Right 45° (Ön-Sağ)", subtype="FILE_PATH", default="")

    # --- SAMPLING & WORKFLOW PARAMETERS ---
    steps: IntProperty(
        name="Sampling Steps",
        description="Albedo diffusion sampling steps",
        default=20,
        min=1,
        max=200,
    )

    guidance: FloatProperty(
        name="Guidance / CFG",
        description="CFG scale; native FLUX.2 uses it only when negative prompt conditioning is enabled",
        default=4.0,
        min=0.0,
        max=30.0,
        step=10,
    )

    view_resolution: EnumProperty(
        name="View Resolution",
        description="Per-camera render resolution (1:1 Square)",
        items=[
            ("256", "256 (Minimum Test)", "Minimum per-view sampling resolution", 0, 3),
            ("512", "512 (Fast Preview)", "Faster sampling", 0, 0),
            ("1024", "1024 (Balanced)", "Default production resolution (1:1 Square)", 0, 1),
            ("2048", "2048 (Ultra Quality)", "High resolution per-view sampling (1:1 Square)", 0, 2),
            ("4096", "4096 (Maximum)", "Maximum per-view sampling resolution (1:1 Square)", 0, 4),
        ],
        default="1024",
        update=_on_view_resolution_changed,
    )

    texture_size: EnumProperty(
        name="Texture Size",
        description="Final baked UV texture resolution",
        items=[
            ("512", "512 (Minimum Test)", "512x512 texture maps", 0, 3),
            ("1024", "1024 (1K)", "1024x1024 texture maps", 0, 0),
            ("2048", "2048 (2K)", "2048x2048 texture maps", 0, 1),
            ("4096", "4096 (4K)", "4096x4096 texture maps", 0, 2),
            ("8192", "8192 (8K)", "8192x8192 texture maps", 0, 4),
        ],
        default="2048",
    )

    uv_mode: EnumProperty(
        name="UV Mode",
        description="Mesh UV unwrapping technique",
        items=[
            ("comfy_gpu", "Comfy GPU", "Fast GPU unwrapper"),
            ("xatlas", "xatlas (CPU)", "CPU xatlas chart packer"),
            ("keep_existing", "Keep Existing UVs", "Use object's existing UV coordinates"),
        ],
        default="comfy_gpu",
    )

    material_apply_mode: EnumProperty(
        name="Material Slot Policy",
        description="Choose how the generated PBR material is applied to existing object material slots",
        items=[
            ("ALL_SLOTS", "Entire Mesh (All Slots)", "Assign the baked PBR atlas to all material slots and faces"),
            ("ACTIVE_SLOT", "Active Slot Only", "Replace only the currently active material slot, preserving other materials"),
            ("NEW_SLOT", "Append New Slot", "Add as a new material slot without altering existing materials"),
        ],
        default="ALL_SLOTS",
    )

    reference_alignment: EnumProperty(
        name="Alignment",
        description="How to align reference image against front silhouette",
        items=[
            ("fit_front_silhouette", "Fit Front Silhouette", "Fit reference to front view"),
            ("center", "Center", "Center reference"),
        ],
        default="fit_front_silhouette",
    )

    seed: IntProperty(
        name="Seed",
        description="Random seed for diffusion sampler",
        default=42,
        min=0,
    )

    lora_albedo_strength: FloatProperty(
        name="Albedo LoRA Strength",
        default=1.0,
        min=0.0,
        max=2.0,
        step=5,
    )

    lora_mr_strength: FloatProperty(
        name="MR LoRA Strength",
        default=1.0,
        min=0.0,
        max=2.0,
        step=5,
    )

    view_weight_power: FloatProperty(
        name="View Weight Power",
        default=4.0,
        min=0.0,
        max=16.0,
        step=10,
    )

    best_view_mix: FloatProperty(
        name="Best View Mix",
        default=0.5,
        min=0.0,
        max=1.0,
        step=5,
    )

    edge_feather_px: FloatProperty(
        name="Edge Feather (px)",
        default=6.0,
        min=0.0,
        max=64.0,
        step=5,
    )

    render_size: IntProperty(name="Geometry Render Size", default=4096, min=512, max=4096, step=512)
    enable_mr: BoolProperty(name="Generate Metallic / Roughness", default=True)
    mr_steps: IntProperty(name="MR Sampling Steps", default=20, min=1, max=200)
    mr_resolution: EnumProperty(name="MR View Resolution", items=[
        (str(value), str(value), "Metallic / roughness sampling resolution") for value in (256, 512, 1024, 2048, 4096)
    ], default="1024")
    use_negative_prompt: BoolProperty(
        name="Enable Negative Prompt / CFG", default=False,
        description="Separate negative conditioning activates FLUX.2 CFG and uses more VRAM and compute",
    )
    drop_background_tokens: BoolProperty(name="Drop Background Tokens", default=True)
    memory_factor: FloatProperty(name="Activation Memory Factor", default=0.0, min=0.0, max=200.0,
        description="Native sampler: 0 selects automatically; higher reserves more activation memory")
    attention: EnumProperty(name="Attention", items=[
        ("ultratex_sparse", "UltraTex Sparse", "Sparse attention used during UltraTex training"),
        ("comfy_default", "ComfyUI Default", "Dense attention using ComfyUI's configured backend"),
    ], default="ultratex_sparse")
    sparse_topk: FloatProperty(name="Sparse Retention", default=0.2, min=0.05, max=1.0, step=5)
    token_chunk: IntProperty(name="Token Chunk", default=8192, min=0, max=131072, step=1024)
    albedo_denoise: FloatProperty(name="Input Denoise", default=1.0, min=0.0, max=1.0,
        description="Manual workflow: lower values preserve more of the captured camera images")
    keep_above: FloatProperty(name="Reprojection Keep Threshold", default=0.75, min=0.0, max=1.01)
    keep_feather: FloatProperty(name="Reprojection Keep Feather", default=0.1, min=0.0, max=0.5)
    view_count: EnumProperty(name="Generated Views", items=[
        ("6", "6", "Canonical views"), ("12", "12", "Canonical and rotated rigs"),
    ], default="12")
    extra_steps: IntProperty(name="Extra Angle Steps", default=20, min=1, max=100)
    extra_angle_mode: EnumProperty(name="Extra Angle Mode", items=[
        ("guided", "Guided", "Reproject first pass into the rotated views"),
        ("independent", "Independent", "Generate rotated views independently"),
    ], default="guided")
    tiled_decode: BoolProperty(name="Tiled VAE Decode", default=True)
    fill_unseen: BoolProperty(name="Fill Unseen Surfaces", default=True)
    blend_mode: EnumProperty(name="Bake Blend", items=[
        (value, value.replace("_", " ").title(), "UV texture blending")
        for value in ("detail_preserving", "reference", "smooth", "legacy")
    ], default="detail_preserving")
    repair_mode: EnumProperty(name="Unseen Surface Repair", items=[
        (value, value.replace("_", " ").title(), "Repair hidden texels after projection")
        for value in ("normal_aware_surface", "nearest_surface", "nearest_in_chart", "none")
    ], default="normal_aware_surface")
    uv_padding: IntProperty(name="UV Padding", default=16, min=0, max=128)


class VIEW3D_PT_motionsmith_surface_base(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Surface'


class VIEW3D_PT_motionsmith_surface_main(VIEW3D_PT_motionsmith_surface_base):
    bl_idname = "VIEW3D_PT_motionsmith_surface_main"
    bl_label = "MotionSmith Surface"

    def draw_header(self, context):
        self.layout.label(text="", icon_value=preferences.get_icon_id())

    def draw(self, context):
        layout = self.layout
        props = context.scene.motionsmith_surface_props
        prefs = preferences.get_preferences(context)
        port = prefs.server_port if prefs else 8188

        # --- SERVER MANAGEMENT SECTION ---
        box = layout.box()
        status = props.server_status
        alive = (status == "ONLINE")

        if status == "ONLINE":
            row = box.row(align=True)
            row.label(text=f"Server: Online (Port {port})", icon="CHECKMARK")
            row.operator("motionsmith_surface.server_status", text="", icon="FILE_REFRESH")
            row.operator("wm.url_open", text="", icon="URL").url = prefs.server_url if prefs else "http://127.0.0.1:8188"

            row = box.row(align=True)
            row.scale_y = 1.2
            row.operator("motionsmith_surface.server_stop", text="Stop Server", icon="PAUSE")
        elif status == "STARTING":
            row = box.row(align=True)
            row.label(text="Server: Starting...", icon="TIME")
            row.operator("motionsmith_surface.server_status", text="", icon="FILE_REFRESH")

            box.label(text="Booting UltraTex & models...", icon="DOT")

            row = box.row(align=True)
            row.scale_y = 1.2
            row.operator("motionsmith_surface.server_stop", text="Cancel / Stop", icon="CANCEL")
        elif status == "STOPPING":
            row = box.row(align=True)
            row.label(text="Server: Stopping...", icon="CANCEL")
        else:  # OFFLINE
            row = box.row(align=True)
            row.label(text="Server: Offline", icon="CANCEL")
            row.operator("motionsmith_surface.server_status", text="", icon="FILE_REFRESH")

            row = box.row(align=True)
            row.scale_y = 1.2
            row.operator("motionsmith_surface.server_start", text="Start Server", icon="PLAY")

            if prefs:
                row_opt = box.row()
                row_opt.prop(prefs, "show_console", text="Open Console Window")

        page_row = layout.row()
        page_row.enabled = not props.is_generating
        page_row.prop(props, "page", expand=True)
        if props.page == "PBR_MATERIAL":
            box = layout.box()
            box.label(text="PBR Material", icon="MATERIAL")
            box.prop(props, "pbr_image")
            box.label(text="Image -> Base Color / Normal / Roughness / Metalness / Height")
            obj = context.active_object
            if obj and obj.type == 'MESH' and obj.mode == 'OBJECT' and obj.data.uv_layers.active:
                box.label(text=f"Apply to: {obj.name}", icon="MESH_DATA")
            else:
                box.label(text="Create material in Blender's material list", icon="MATERIAL")
            row = layout.row()
            row.enabled = bool(alive and props.pbr_image.strip() and not props.is_generating)
            row.scale_y = 1.6
            row.operator("motionsmith_surface.generate_material", text="Generate PBR Material", icon="MATERIAL")
            if props.is_generating:
                layout.operator("motionsmith_surface.cancel_generation", text="Cancel", icon="CANCEL")
            if props.last_prompt_id:
                layout.operator("motionsmith_surface.recover_result", text="Check / Apply Last Result", icon="FILE_REFRESH")
            layout.label(text=props.generation_status, icon="INFO")
            if props.is_generating:
                if props.generation_progress >= 0:
                    layout.progress(factor=props.generation_progress, type='BAR', text="Current stage")
                if props.generation_remaining:
                    layout.label(text=props.generation_remaining)
            return

        # --- TARGET MESH SECTION ---
        box = layout.box()
        box.label(text="Target Mesh", icon="MESH_DATA")
        
        active_obj = context.active_object
        has_mesh = active_obj is not None and active_obj.type == 'MESH'
        
        if has_mesh:
            v_count = len(active_obj.data.vertices)
            p_count = len(active_obj.data.polygons)
            box.label(text=f"Selected: {active_obj.name}", icon="OBJECT_DATAMODE")
            box.label(text=f"Geometry: {v_count:,} verts | {p_count:,} faces", icon="DOT")
        else:
            box.alert = True
            box.label(text="No mesh selected! Select a mesh in viewport.", icon="ERROR")

        box = layout.box()
        box.label(text="Texture Workflow", icon="RENDER_STILL")
        workflow_row = box.row()
        workflow_row.enabled = not props.is_generating
        workflow_row.prop(props, "texture_quality", text="Workflow")
        if props.texture_quality == "10_VIEWS":
            box.prop(props, "multiview_denoise", text="Pass 2 Denoise")
            box.label(text=("Prompt + geometry" if props.input_mode == "PROMPT" else "1 reference") + " -> 6 + 4 generated views", icon="INFO")
        elif props.texture_quality == "MANUAL_10_VIEWS":
            if props.manual_source == "CAMERAS":
                box.label(text="10 Blender camera renders -> 10 workflow image inputs", icon="INFO")
            elif props.manual_source == "FOLDER":
                box.label(text="10 photos from folder -> 10 workflow image inputs", icon="INFO")
            else:
                box.label(text="10 individual photos -> 10 workflow image inputs", icon="INFO")
            box.label(text="Captured albedo is baked; AI predicts optional MR", icon="DOT")
        elif props.texture_quality == "LOW_VRAM_GGUF":
            box.label(text="Prompt + geometry with modular GGUF generation" if props.input_mode == "PROMPT" else "Single reference with modular GGUF generation", icon="INFO")
        else:
            box.label(text=("Prompt + geometry" if props.input_mode == "PROMPT" else "1 reference") + " -> 6 generated canonical views", icon="INFO")

        if props.texture_quality == "MANUAL_10_VIEWS":
            box = layout.box()
            box.label(text="Manual 10 Views Input", icon="IMAGE_DATA")
            box.prop(props, "manual_source", text="Source")

            if props.manual_source == "CAMERAS":
                box.label(text="Front / Right / Back / Left / Top / Bottom + 4 diagonals", icon="DOT")
                row = box.row(align=True)
                setup_row = row.row(align=True)
                setup_row.enabled = bool(has_mesh and not props.is_generating)
                setup_row.operator("motionsmith_surface.setup_cameras", text="Setup 10 Cameras", icon="CON_CAMERASOLVER")

                selected_cam = None
                if context.active_object and context.active_object.type == 'CAMERA':
                    selected_cam = context.active_object
                elif context.scene.camera:
                    selected_cam = context.scene.camera

                view_label = f"View ({selected_cam.name})" if selected_cam else "View Camera"
                op_view = row.operator("motionsmith_surface.view_camera", text=view_label, icon="VIEW_CAMERA")
                op_view.camera_name = selected_cam.name if selected_cam else ""

                grid = box.grid_flow(columns=3, align=True)
                cam_buttons = [
                    ("Front", "MS_Cam_0_Front"),
                    ("Right", "MS_Cam_3_Right"),
                    ("Back", "MS_Cam_2_Back"),
                    ("Left", "MS_Cam_1_Left"),
                    ("Top", "MS_Cam_4_Top"),
                    ("Bottom", "MS_Cam_5_Bottom"),
                    ("Front Right 45°", "MS_Cam_9_FrontRight"),
                    ("Back Right 135°", "MS_Cam_8_BackRight"),
                    ("Back Left 225°", "MS_Cam_7_BackLeft"),
                    ("Front Left 315°", "MS_Cam_6_FrontLeft"),
                ]
                for label, cname in cam_buttons:
                    is_active = bool(context.scene.camera and context.scene.camera.name == cname)
                    btn = grid.operator("motionsmith_surface.view_camera", text=label, depress=is_active)
                    btn.camera_name = cname
            elif props.manual_source == "FOLDER":
                box.prop(props, "manual_images_dir")
                box.label(text="Folder should contain 10 view photos (front, left, back, ...)", icon="INFO")
            else:  # FILES
                box.label(text="Specify 10 view image files:", icon="FILE_IMAGE")
                col_files = box.column(align=True)
                col_files.prop(props, "manual_image_0_front")
                col_files.prop(props, "manual_image_1_left")
                col_files.prop(props, "manual_image_2_back")
                col_files.prop(props, "manual_image_3_right")
                col_files.prop(props, "manual_image_4_top")
                col_files.prop(props, "manual_image_5_bottom")
                col_files.prop(props, "manual_image_6_front_left")
                col_files.prop(props, "manual_image_7_back_left")
                col_files.prop(props, "manual_image_8_back_right")
                col_files.prop(props, "manual_image_9_front_right")

        elif props.input_mode != "PROMPT":
            # --- CAMERA & CAPTURE SETUP ---
            box = layout.box()
            box.label(text="Camera & Capture Setup", icon="CAMERA_DATA")
            box.label(text="Setup: 1 Front Reference")

            selected_cam = None
            if context.active_object and context.active_object.type == 'CAMERA':
                selected_cam = context.active_object
            else:
                for o in context.selected_objects:
                    if o.type == 'CAMERA':
                        selected_cam = o
                        break
            if not selected_cam and context.scene.camera:
                selected_cam = context.scene.camera

            row = box.row(align=True)
            setup_row = row.row(align=True)
            setup_row.enabled = bool(has_mesh and not props.is_generating)
            setup_row.operator("motionsmith_surface.setup_cameras", text="Setup Camera (1 Cam)", icon="CON_CAMERASOLVER")

            view_label = f"View ({selected_cam.name})" if selected_cam else "View Camera"
            op_view = row.operator("motionsmith_surface.view_camera", text=view_label, icon="VIEW_CAMERA")
            op_view.camera_name = selected_cam.name if selected_cam else ""

            box.label(text="1 Front Camera -> Feeds ComfyUI LoadImage", icon="DOT")
            box.label(text="AI synthesizes full 360° PBR from this camera visual", icon="INFO")

        else:
            box = layout.box()
            box.label(text="Mesh geometry supplies the shape; camera capture is skipped.", icon="MESH_DATA")

        # --- TEXT GUIDANCE & PROMPTS ---
        box = layout.box()
        manual = props.texture_quality == "MANUAL_10_VIEWS"
        box.label(text="Camera Images + Optional MR Prompt" if manual else "Generation Inputs", icon="FONT_DATA")
        if not manual:
            mode_row = box.row()
            mode_row.enabled = not props.is_generating
            mode_row.prop(props, "input_mode")
        use_text = manual or props.input_mode != "IMAGE"
        if use_text:
            box.prop(props, "style_preset", text="Preset")
            if not manual and props.input_mode == "BOTH" and not props.positive_prompt.strip():
                box.label(text="Empty prompt: use image guidance only.", icon="INFO")
            col_prompt = box.column(align=True)
            col_prompt.label(text="Positive Prompt:")
            col_prompt.prop(props, "positive_prompt", text="")
            col_prompt.prop(props, "use_negative_prompt")
            negative_row = col_prompt.row()
            negative_row.enabled = props.use_negative_prompt
            negative_row.prop(props, "negative_prompt", text="Negative Prompt")
        else:
            box.label(text="Text prompts are not sent in Image Only mode.", icon="INFO")
        if not manual and props.input_mode != "PROMPT":
            box.prop(props, "custom_reference_image")
            if not props.custom_reference_image.strip():
                box.label(text="No file selected: use the front-camera capture.", icon="INFO")
        elif not manual:
            box.label(text="No image or camera capture is used as a reference.", icon="INFO")

        # --- ACTION BUTTON ---
        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.8
        col.enabled = bool(has_mesh and alive and not props.is_generating)
        col.operator("motionsmith_surface.generate_texture", text="Generate Texture", icon="SHADING_RENDERED")
        if props.is_generating:
            layout.operator("motionsmith_surface.cancel_generation", text="Cancel", icon="CANCEL")
        if props.last_prompt_id:
            layout.operator("motionsmith_surface.recover_result", text="Check / Apply Last Result", icon="FILE_REFRESH")

        # Status box
        status_box = layout.box()
        status_box.label(text=f"Status: {props.generation_status}", icon="INFO")
        if props.is_generating:
            if props.generation_progress >= 0:
                status_box.progress(factor=props.generation_progress, type='BAR', text="Current stage")
            if props.generation_remaining:
                status_box.label(text=props.generation_remaining)


class VIEW3D_PT_motionsmith_surface_models(VIEW3D_PT_motionsmith_surface_base):
    bl_idname = "VIEW3D_PT_motionsmith_surface_models"
    bl_label = "Model Selection"
    bl_parent_id = "VIEW3D_PT_motionsmith_surface_main"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.motionsmith_surface_props.page == "TEXTURE"

    def draw(self, context):
        layout = self.layout
        props = context.scene.motionsmith_surface_props

        col = layout.column(align=True)
        row = col.row(align=True)
        row.label(text="Installed Models", icon="SETTINGS")
        row.operator("motionsmith_surface.refresh_models", text="", icon="FILE_REFRESH")

        col.prop(props, "unet_model")
        col.prop(props, "clip_model")
        col.prop(props, "vae_model")
        col.prop(props, "decoder_model")
        col.separator()
        col.prop(props, "lora_albedo_model")
        col.prop(props, "lora_mr_model")
        col.prop(props, "bg_removal_model")


class VIEW3D_PT_motionsmith_surface_workflow_settings(VIEW3D_PT_motionsmith_surface_base):
    bl_idname = "VIEW3D_PT_motionsmith_surface_workflow_settings"
    bl_label = "Workflow Parameters"
    bl_parent_id = "VIEW3D_PT_motionsmith_surface_main"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.motionsmith_surface_props.page == "TEXTURE"

    def draw(self, context):
        layout = self.layout
        props = context.scene.motionsmith_surface_props

        col = layout.column(align=True)
        if props.texture_quality != "MANUAL_10_VIEWS":
            col.prop(props, "steps", text="Albedo Steps")
        if props.texture_quality == "LOW_VRAM_GGUF":
            col.label(text="GGUF sampling: 1–100 steps", icon="INFO")
        col.prop(props, "guidance")
        col.prop(props, "seed")

        col.separator()
        col.prop(props, "view_resolution")
        col.prop(props, "enable_mr")
        mr_col = col.column(align=True)
        mr_col.enabled = props.enable_mr
        mr_col.prop(props, "mr_steps")
        mr_col.prop(props, "mr_resolution")
        col.prop(props, "texture_size")
        col.prop(props, "uv_mode")
        col.prop(props, "material_apply_mode")
        if props.texture_quality == "LOW_VRAM_GGUF":
            col.prop(props, "view_count")
            col.prop(props, "uv_padding")
        else:
            col.prop(props, "render_size")
            col.prop(props, "reference_alignment")


class VIEW3D_PT_motionsmith_surface_advanced(VIEW3D_PT_motionsmith_surface_base):
    bl_idname = "VIEW3D_PT_motionsmith_surface_advanced"
    bl_label = "Advanced Tuning"
    bl_parent_id = "VIEW3D_PT_motionsmith_surface_main"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.motionsmith_surface_props.page == "TEXTURE"

    def draw(self, context):
        layout = self.layout
        props = context.scene.motionsmith_surface_props

        col = layout.column(align=True)
        if props.texture_quality != "MANUAL_10_VIEWS":
            col.prop(props, "lora_albedo_strength")
        col.prop(props, "lora_mr_strength")
        col.separator()
        if props.texture_quality == "LOW_VRAM_GGUF":
            col.prop(props, "sparse_topk")
            col.prop(props, "tiled_decode")
            col.prop(props, "fill_unseen")
            col.prop(props, "blend_mode")
            col.prop(props, "repair_mode")
            if props.view_count == "12":
                col.prop(props, "extra_angle_mode")
                col.prop(props, "extra_steps")
                col.prop(props, "multiview_denoise", text="Extra Angle Denoise")
        else:
            col.prop(props, "drop_background_tokens")
            col.prop(props, "memory_factor")
            col.prop(props, "attention")
            col.prop(props, "sparse_topk")
            col.prop(props, "token_chunk")
            if props.texture_quality == "10_VIEWS":
                col.prop(props, "keep_above")
                col.prop(props, "keep_feather")
            col.separator()
            col.prop(props, "view_weight_power")
            col.prop(props, "best_view_mix")
            col.prop(props, "edge_feather_px")


classes = (
    MotionSmithSurfaceSceneProperties,
    VIEW3D_PT_motionsmith_surface_main,
    VIEW3D_PT_motionsmith_surface_models,
    VIEW3D_PT_motionsmith_surface_workflow_settings,
    VIEW3D_PT_motionsmith_surface_advanced,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.motionsmith_surface_props = PointerProperty(type=MotionSmithSurfaceSceneProperties)


def unregister():
    if hasattr(bpy.types.Scene, "motionsmith_surface_props"):
        del bpy.types.Scene.motionsmith_surface_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
