"""MotionSmith Surface - Calibrated Camera Manager.

Creates, aligns, and renders calibrated camera views matching TexVerse / UltraTex canonical camera conventions.
Single-reference workflows capture the front view; the manual workflow captures
the six canonical views and four diagonal views in UltraTex's native rig order.
"""

from __future__ import annotations

import math
import os
import re
from typing import Dict, List, Optional, Tuple

import bpy
from mathutils import Euler, Vector

# TexVerse / UltraTex camera constants
CAM_DIST_NORM = 1.67  # Distance for normalized radius = 0.5
TEXVERSE_FOV_DEG = math.degrees(2.0 * math.atan(4096.0 / (2.0 * 6400.0)))
COLLECTION_NAME = "MotionSmith_Cameras"

# 6 canonical orientations (order: 0=front, 1=left, 2=back, 3=right, 4=top, 5=bottom)
# Poses are defined in Blender Z-up frame looking towards center (0, 0, 0)
VIEW_CONFIGS = [
    ("front", Vector((0, -1, 0)), Euler((math.pi / 2, 0, 0), "XYZ")),
    ("left", Vector((-1, 0, 0)), Euler((math.pi / 2, 0, -math.pi / 2), "XYZ")),
    ("back", Vector((0, 1, 0)), Euler((math.pi / 2, 0, math.pi), "XYZ")),
    ("right", Vector((1, 0, 0)), Euler((math.pi / 2, 0, math.pi / 2), "XYZ")),
    ("top", Vector((0, 0, 1)), Euler((0, 0, 0), "XYZ")),
    ("bottom", Vector((0, 0, -1)), Euler((math.pi, 0, math.pi), "XYZ")),
]

# UltraTexRotateRig(+45) rotates the OBJECT, so its effective camera angles are
# 315, 225, 135, 45 in canonical front/left/back/right order.
MANUAL_VIEW_CONFIGS = VIEW_CONFIGS + [
    (name, Vector((math.sin(math.radians(angle)), -math.cos(math.radians(angle)), 0)),
     Euler((math.pi / 2, 0, math.radians(angle)), "XYZ"))
    for name, angle in [("front_left", 315), ("back_left", 225),
                        ("back_right", 135), ("front_right", 45)]
]
MANUAL_VIEW_NAMES = tuple(config[0] for config in MANUAL_VIEW_CONFIGS)

# Primary keyword patterns for identifying the 10 views from filenames (English, Turkish, degrees, numbers)
MANUAL_VIEW_SPECS = [
    (0, "front", ["front", "0deg", "0 deg", "cam 0", "cam_0", "view 0", "view_0", "on 0deg", "on 0 deg", "on 0", "on"]),
    (1, "left", ["left", "270deg", "270 deg", "cam 1", "cam_1", "view 1", "view_1", "sol 270deg", "sol 270 deg", "sol 270", "sol"]),
    (2, "back", ["back", "rear", "180deg", "180 deg", "cam 2", "cam_2", "view 2", "view_2", "arka 180deg", "arka 180 deg", "arka 180", "arka"]),
    (3, "right", ["right", "90deg", "90 deg", "cam 3", "cam_3", "view 3", "view_3", "sag 90deg", "sag 90 deg", "sag 90", "sag"]),
    (4, "top", ["top", "up", "cam 4", "cam_4", "view 4", "view_4", "ustten", "ust", "tepe"]),
    (5, "bottom", ["bottom", "down", "cam 5", "cam_5", "view 5", "view_5", "alttan", "alt", "taban"]),
    (6, "front_left", ["front left", "front_left", "frontleft", "315deg", "315 deg", "cam 6", "cam_6", "view 6", "view_6", "on sol", "on_sol", "on sol capraz"]),
    (7, "back_left", ["back left", "back_left", "backleft", "225deg", "225 deg", "cam 7", "cam_7", "view 7", "view_7", "arka sol", "arka_sol", "arka sol capraz"]),
    (8, "back_right", ["back right", "back_right", "backright", "135deg", "135 deg", "cam 8", "cam_8", "view 8", "view_8", "arka sag", "arka_sag", "arka sag capraz"]),
    (9, "front_right", ["front right", "front_right", "frontright", "45deg", "45 deg", "cam 9", "cam_9", "view 9", "view_9", "on sag", "on_sag", "on sag capraz"]),
]


def normalize_view_text(text: str) -> str:
    """Normalize filename text for robust token and regex matching across English/Turkish names."""
    t = text.lower()
    t = t.replace('°', 'deg').replace('–', '-').replace('—', '-')
    t = t.replace('ı', 'i').replace('ğ', 'g').replace('ü', 'u').replace('ş', 's').replace('ö', 'o').replace('ç', 'c')
    t = re.sub(r'[^a-z0-9]+', ' ', t).strip()
    return t


def find_10_views_in_folder(folder: str) -> List[str]:
    """Scan folder and strictly match exactly 10 unique calibrated view images.
    
    Supports English canonical names, Turkish names ('ön', 'sağ', 'arka', 'sol', 'üst', 'alt'),
    degree indicators ('0°', '90°', '180°', '270°', '45°', '135°', '225°', '315°'), and numeric indexing.
    Guarantees 1-to-1 uniqueness: no image file is assigned to multiple angles.
    Raises ValueError on missing views without silent wrong-angle fallbacks.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"10 Views Folder not found: {folder}")

    image_exts = {".png", ".jpg", ".jpeg", ".webp"}
    files = [f for f in sorted(os.listdir(folder)) if os.path.splitext(f)[1].lower() in image_exts]
    if len(files) < 10:
        raise ValueError(f"Folder '{folder}' contains only {len(files)} image(s); exactly 10 calibrated views are required.")

    file_normalized = {f: normalize_view_text(os.path.splitext(f)[0]) for f in files}

    # Match compound diagonals first (6, 7, 8, 9) before simple directions (0, 1, 2, 3), then extremes (4, 5)
    match_order = [6, 7, 8, 9, 4, 5, 1, 2, 3, 0]
    assigned: Dict[int, str] = {}
    used_files = set()

    for idx in match_order:
        spec_idx, key, patterns = MANUAL_VIEW_SPECS[idx]
        best_match = None
        for pat in patterns:
            pat_norm = normalize_view_text(pat)
            regex = r'\b' + re.escape(pat_norm).replace(r'\ ', r'[\s_-]+') + r'\b'
            for f in files:
                if f in used_files:
                    continue
                if re.search(regex, file_normalized[f]):
                    best_match = f
                    break
            if best_match:
                break
        if best_match:
            assigned[idx] = best_match
            used_files.add(best_match)

    # Validate that every single index 0..9 has a matched unique file
    missing = [MANUAL_VIEW_SPECS[idx][1] for idx in range(10) if idx not in assigned]
    if missing:
        unassigned_files = [f for f in files if f not in used_files]
        raise ValueError(
            f"Could not automatically match all 10 views in '{folder}'.\n"
            f"Missing views: {', '.join(missing)}.\n"
            f"Matched {len(assigned)}/10 views. Unassigned files in folder: {', '.join(unassigned_files) if unassigned_files else 'None'}."
        )

    # Return full absolute paths in canonical 0..9 index order
    return [os.path.join(folder, assigned[idx]) for idx in range(10)]


def get_capture_mode(props) -> str:
    """The selected workflow determines how many input photographs it consumes."""
    return "MANUAL_10" if props.texture_quality == "MANUAL_10_VIEWS" else "SINGLE"


def _view_configs(mode):
    if mode == "MANUAL_10":
        return MANUAL_VIEW_CONFIGS
    if mode == "MULTI":  # Existing scripts can still request the canonical rig.
        return VIEW_CONFIGS
    return VIEW_CONFIGS[:1]


def camera_name(mode, index, view_name):
    return "MS_Cam_Front" if mode == "SINGLE" else f"MS_Cam_{index}_{view_name.title().replace('_', '')}"


def get_mesh_bounds(obj: bpy.types.Object) -> Tuple[Vector, float]:
    """Match UltraTex normalization of the evaluated mesh exported in world space."""
    if not obj or obj.type != "MESH":
        return Vector((0.0, 0.0, 0.0)), 1.0

    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        used = {index for polygon in mesh.polygons for index in polygon.vertices}
        points = [evaluated.matrix_world @ mesh.vertices[index].co for index in used]
    finally:
        evaluated.to_mesh_clear()
    if not points:
        return obj.matrix_world.translation.copy(), 1.0
    low = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
    high = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
    center = (low + high) * 0.5
    radius = max((point - center).length for point in points)
    if radius < 0.001:
        radius = 1.0
    return center, radius


def get_or_create_collection(context: bpy.types.Context) -> bpy.types.Collection:
    """Get or create the MotionSmith_Cameras collection in the active scene."""
    scene = context.scene
    for col in scene.collection.children:
        if col.name == COLLECTION_NAME:
            return col

    col = bpy.data.collections.new(COLLECTION_NAME)
    scene.collection.children.link(col)
    return col


def setup_calibrated_cameras(
    context: bpy.types.Context,
    mode: str = "SINGLE",
    target_obj: bpy.types.Object | None = None,
) -> List[bpy.types.Object]:
    """Create or update calibrated camera(s) framing the target mesh.
    
    mode: "SINGLE", "MANUAL_10", or legacy "MULTI" (six canonical cameras).
    Returns list of camera objects.
    """
    if target_obj is None:
        target_obj = context.active_object
    if not target_obj or target_obj.type != "MESH":
        return []

    center, radius = get_mesh_bounds(target_obj)
    # Calculate calibrated distance: scale distance proportionally to mesh radius
    dist = CAM_DIST_NORM * (radius / 0.5)

    col = get_or_create_collection(context)
    created_cams: List[bpy.types.Object] = []

    configs_to_use = _view_configs(mode)
    wanted_names = {camera_name(mode, index, config[0]) for index, config in enumerate(configs_to_use)}
    # Only remove cameras owned by this add-on's collection.
    for old_cam in list(col.objects):
        if old_cam.type == "CAMERA" and old_cam.name.startswith("MS_Cam_") and old_cam.name not in wanted_names:
            old_data = old_cam.data
            bpy.data.objects.remove(old_cam, do_unlink=True)
            if old_data.users == 0:
                bpy.data.cameras.remove(old_data)

    for idx, (view_name, dir_vec, euler_rot) in enumerate(configs_to_use):
        cam_name = camera_name(mode, idx, view_name)

        # Find existing or create new
        cam_obj = bpy.data.objects.get(cam_name)
        if cam_obj is None or cam_obj.type != "CAMERA":
            cam_data = bpy.data.cameras.new(cam_name)
            cam_obj = bpy.data.objects.new(cam_name, cam_data)
            col.objects.link(cam_obj)
        else:
            cam_data = cam_obj.data

        # Configure calibrated camera optics
        cam_data.lens_unit = "FOV"
        cam_data.angle_y = math.radians(TEXVERSE_FOV_DEG)
        cam_data.sensor_fit = "VERTICAL"
        cam_data.passepartout_alpha = 0.9
        cam_data.clip_start = max(0.0001, dist * 0.01)
        cam_data.clip_end = max(100.0, dist * 5.0)

        # Position and rotate camera
        cam_obj.location = center + dir_vec * dist
        cam_obj.rotation_euler = euler_rot

        created_cams.append(cam_obj)

    # Set active scene camera to front camera
    if created_cams:
        context.scene.camera = created_cams[0]

    # Enforce 1:1 square render resolution in Blender scene matching view_resolution
    props = getattr(context.scene, "motionsmith_surface_props", None)
    res = int(props.view_resolution) if (props and hasattr(props, "view_resolution")) else 1024
    context.scene.render.resolution_x = res
    context.scene.render.resolution_y = res
    context.scene.render.resolution_percentage = 100
    context.scene.render.pixel_aspect_x = 1.0
    context.scene.render.pixel_aspect_y = 1.0

    return created_cams


def _composite_render_to_white_bg(image_path: str):
    """Composites rendered image over pure white background while retaining the alpha channel.

    UltraTex & TexVerse camera convention:
    1. Background pixels outside the object silhouette must have RGB = (255, 255, 255)
       so that `(init_np[v] < 245)` in `_check_init_alignment` correctly recognizes them as background
       and does not falsely flag them as out-of-silhouette content.
    2. The alpha channel must remain intact so ComfyUI LoadImage MASK (1.0 - alpha)
       provides exact sub-pixel foreground/background segmentation for UltraTexPrep.
    """
    import numpy as np

    # Blender bundles numpy; Pillow is not available in every Blender install.
    image = bpy.data.images.load(image_path, check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "STRAIGHT"
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgba = pixels.reshape(-1, 4)
        alpha = rgba[:, 3:4]
        rgba[:, :3] = rgba[:, :3] * alpha + (1.0 - alpha)
        image.pixels.foreach_set(pixels)
        image.file_format = "PNG"
        image.save(filepath=image_path)
    finally:
        bpy.data.images.remove(image)


def render_calibrated_views(
    context: bpy.types.Context,
    output_dir: str,
    mode: str = "SINGLE",
    resolution: int = 1024,
    target_obj: bpy.types.Object | None = None,
) -> List[str]:
    """Render the calibrated camera(s) directly to PNG files in output_dir.
    
    Returns list of rendered filenames (relative to output_dir).
    """
    os.makedirs(output_dir, exist_ok=True)
    scene = context.scene
    orig_cam = scene.camera
    original_camera_name = orig_cam.name if orig_cam else None

    # Save original render settings BEFORE any camera setup modifies them
    orig_res_x = scene.render.resolution_x
    orig_res_y = scene.render.resolution_y
    orig_res_pct = scene.render.resolution_percentage
    orig_film_trans = scene.render.film_transparent
    orig_use_comp = scene.render.use_compositing
    orig_format = scene.render.image_settings.file_format
    orig_color = scene.render.image_settings.color_mode
    orig_filepath = scene.render.filepath
    orig_use_border = scene.render.use_border
    orig_crop = scene.render.use_crop_to_border
    orig_pixel_aspect = (scene.render.pixel_aspect_x, scene.render.pixel_aspect_y)

    if target_obj is None:
        target_obj = context.active_object
    cams = setup_calibrated_cameras(context, mode=mode, target_obj=target_obj)
    if not cams:
        return []

    hidden_objects = []
    modifier_states = [(modifier, modifier.show_render, getattr(modifier, "render_levels", None))
                       for modifier in target_obj.modifiers]

    rendered_files: List[str] = []
    temp_light_obj = None
    temp_light_data = None

    try:
        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        # Bypass any scene compositor node graph to avoid empty/intercepted renders
        scene.render.use_compositing = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.use_border = False
        scene.render.use_crop_to_border = False
        scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.0
        for other in scene.objects:
            if other != target_obj and other.type in {"MESH", "CURVE", "SURFACE", "META", "FONT", "VOLUME", "POINTCLOUD", "GREASEPENCIL"}:
                hidden_objects.append((other, other.hide_render))
                other.hide_render = True
        hidden_objects.append((target_obj, target_obj.hide_render))
        target_obj.hide_render = False
        # Match the viewport-evaluated mesh sent to ComfyUI, then restore render settings.
        for modifier, _, _ in modifier_states:
            modifier.show_render = modifier.show_viewport
            if hasattr(modifier, "render_levels") and hasattr(modifier, "levels"):
                modifier.render_levels = modifier.levels

        # Attach a soft camera-following headlight so all 6 viewpoints are properly illuminated
        center, radius = get_mesh_bounds(target_obj)
        dist = CAM_DIST_NORM * (radius / 0.5)
        temp_light_data = bpy.data.lights.new(name="MS_TempHeadlight", type='POINT')
        temp_light_data.energy = 500.0 * max(1.0, (dist / 3.34) ** 2)
        temp_light_data.shadow_soft_size = 0.5
        temp_light_obj = bpy.data.objects.new(name="MS_TempHeadlight", object_data=temp_light_data)
        scene.collection.objects.link(temp_light_obj)

        for idx, cam in enumerate(cams):
            view_name = _view_configs(mode)[idx][0]
            filename = "blender_view_front.png" if mode == "SINGLE" else f"blender_view_{idx}_{view_name}.png"
            full_path = os.path.join(output_dir, filename)

            scene.camera = cam
            scene.render.filepath = full_path

            # Position headlight slightly offset from camera view
            if temp_light_obj is not None:
                offset = cam.matrix_world.to_3x3() @ Vector((0.3, -0.2, 0.5))
                temp_light_obj.location = cam.location + offset

            context.view_layer.update()

            # Render still frame
            bpy.ops.render.render(write_still=True)
            if os.path.isfile(full_path):
                _composite_render_to_white_bg(full_path)
                rendered_files.append(filename)

    finally:
        for modifier, visible, levels in modifier_states:
            modifier.show_render = visible
            if levels is not None:
                modifier.render_levels = levels
        # Clean up temporary light
        if temp_light_obj is not None:
            try:
                if temp_light_obj.name in scene.collection.objects:
                    scene.collection.objects.unlink(temp_light_obj)
                bpy.data.objects.remove(temp_light_obj)
            except Exception:
                pass
        if temp_light_data is not None:
            try:
                bpy.data.lights.remove(temp_light_data)
            except Exception:
                pass

        # Restore original render settings
        scene.camera = (bpy.data.objects.get(original_camera_name) or cams[0]) if original_camera_name else None
        scene.render.resolution_x = orig_res_x
        scene.render.resolution_y = orig_res_y
        scene.render.resolution_percentage = orig_res_pct
        scene.render.film_transparent = orig_film_trans
        scene.render.use_compositing = orig_use_comp
        scene.render.image_settings.file_format = orig_format
        scene.render.image_settings.color_mode = orig_color
        scene.render.filepath = orig_filepath
        scene.render.use_border = orig_use_border
        scene.render.use_crop_to_border = orig_crop
        scene.render.pixel_aspect_x, scene.render.pixel_aspect_y = orig_pixel_aspect
        for other, hidden in hidden_objects:
            other.hide_render = hidden

    return rendered_files
