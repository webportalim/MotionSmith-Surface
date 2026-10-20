"""MotionSmith Surface - Blender Addon Entry Point.

Blender 5.x compatible AI 3D texture generation addon using UltraTex & ComfyUI.
"""

from __future__ import annotations

bl_info = {
    "name": "MotionSmith Surface",
    "author": "MotionSmith",
    "version": (0, 1, 1),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Surface",
    "description": "AI PBR Texturing and Material Generation for Blender",
    "category": "3D View",
}

# Blender reloads the package entry point, but not its imported submodules.
if "bpy" in locals():
    import importlib
    import sys
    for _name in ("model_catalog", "preferences", "client", "workflow", "camera_utils",
                  "material_utils", "uv_transfer", "ui_panel", "operators"):
        _module = sys.modules.get(f"{__package__}.{_name}")
        if _module is not None:
            importlib.reload(_module)

import bpy
from bpy.app.handlers import persistent

from . import preferences
from . import ui_panel
from . import operators
from . import server_manager


import threading

_cached_server_state = "OFFLINE"
_poll_in_flight = False


def _bg_poll_server(port, url):
    global _cached_server_state, _poll_in_flight
    try:
        state = server_manager.get_server_state(port=port, url=url)
        _cached_server_state = state
    except Exception:
        _cached_server_state = "OFFLINE"
    finally:
        _poll_in_flight = False


@persistent
def _on_blend_file_load(dummy=None):
    """Reset and verify server status whenever any blend file is opened."""
    try:
        prefs = preferences.get_preferences()
        port = prefs.server_port if prefs else 8188
        url = prefs.server_url if prefs else f"http://127.0.0.1:{port}"
        t = threading.Thread(target=_bg_poll_server, args=(port, url), daemon=True)
        t.start()
        for scene in bpy.data.scenes:
            if hasattr(scene, "motionsmith_surface_props"):
                props = scene.motionsmith_surface_props
                props.is_generating = False
    except Exception:
        pass


def _server_poll_timer():
    """Background timer to keep server lifecycle badge accurate without lagging UI."""
    global _poll_in_flight, _cached_server_state
    try:
        if bpy.app.background:
            return None

        prefs = preferences.get_preferences()
        port = prefs.server_port if prefs else 8188
        url = prefs.server_url if prefs else f"http://127.0.0.1:{port}"

        if not _poll_in_flight:
            _poll_in_flight = True
            t = threading.Thread(target=_bg_poll_server, args=(port, url), daemon=True)
            t.start()

        state = _cached_server_state
        alive = (state == "ONLINE")
        for scene in bpy.data.scenes:
            if hasattr(scene, "motionsmith_surface_props"):
                props = scene.motionsmith_surface_props
                changed = False
                if props.server_status != state:
                    props.server_status = state
                    changed = True
                if props.server_online != alive:
                    props.server_online = alive
                    changed = True
                if changed:
                    operators.tag_redraw()
    except Exception:
        pass
    return 2.0  # Poll every 2 seconds


def register():
    preferences.register()
    ui_panel.register()
    operators.register()

    # Register persistent file open handler
    if _on_blend_file_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_blend_file_load)

    # Initial server check on load
    try:
        prefs = preferences.get_preferences()
        state = server_manager.get_server_state(port=prefs.server_port if prefs else 8188)
        for scene in bpy.data.scenes:
            if hasattr(scene, "motionsmith_surface_props"):
                props = scene.motionsmith_surface_props
                props.server_status = state
                props.server_online = (state == "ONLINE")
    except Exception:
        pass

    if not bpy.app.background:
        if not bpy.app.timers.is_registered(_server_poll_timer):
            bpy.app.timers.register(_server_poll_timer, first_interval=1.0)


def unregister():
    if _on_blend_file_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_blend_file_load)

    if bpy.app.timers.is_registered(_server_poll_timer):
        bpy.app.timers.unregister(_server_poll_timer)

    operators.unregister()
    ui_panel.unregister()
    preferences.unregister()


if __name__ == "__main__":
    register()
