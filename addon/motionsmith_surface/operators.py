"""MotionSmith Surface - Blender Operators."""

import os
import time
import uuid
import shutil
import threading
from types import SimpleNamespace
import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from . import camera_utils
from . import client
from . import material_utils
from . import model_catalog
from . import preferences
from . import server_manager
from . import workflow
from . import uv_transfer


def tag_redraw():
    """Trigger redraw of 3D viewports so button and status changes update immediately."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


_ACTIVE_JOBS = {}
_UV_TRANSFER_CHECKS = {}


class MOTIONSMITH_SURFACE_OT_uv_transfer_check(Operator):
    bl_idname = "motionsmith_surface.uv_transfer_check"
    bl_label = "UV Transfer Check"
    bl_description = "Check GLB/Trimesh UV transport offline, without AI or changing the source mesh"

    action: StringProperty(default="VALIDATE", options={'HIDDEN'})

    def execute(self, context):
        import json
        import subprocess
        props = context.scene.motionsmith_surface_props
        key = context.scene.as_pointer()
        state = _UV_TRANSFER_CHECKS.get(key)
        try:
            if props.is_generating:
                raise ValueError("Wait for the current generation to finish.")
            if self.action == 'CLEAR':
                if state:
                    uv_transfer.clear_preview(state)
                props.uv_transfer_status = "Checker preview removed."
                return {'FINISHED'}
            if self.action == 'VALIDATE':
                if state:
                    uv_transfer.clear_preview(state)
                _UV_TRANSFER_CHECKS.pop(key, None)
                obj = context.active_object
                if not obj or obj.type != 'MESH':
                    raise ValueError("Select the original mesh.")
                uv_name = props.uv_transfer_uv or (obj.data.uv_layers.active.name
                                                    if obj.data.uv_layers.active else "")
                prefs = preferences.get_preferences(context)
                comfyui_dir = preferences.get_comfyui_dir(context)
                python = bpy.path.abspath(prefs.python_executable) if prefs and prefs.python_executable else os.path.join(
                    comfyui_dir, '.venv', 'Scripts' if os.name == 'nt' else 'bin',
                    'python.exe' if os.name == 'nt' else 'python')
                if not os.path.isfile(python):
                    raise FileNotFoundError("Configure the ComfyUI Python executable first.")
                directory = os.path.join(comfyui_dir, 'input', 'MotionSmith_Surface',
                                         'uv_check_' + uuid.uuid4().hex[:12])
                state = uv_transfer.export_snapshot(context, obj, uv_name, directory)
                result = subprocess.run(
                    [python, os.path.abspath(uv_transfer.__file__), directory],
                    capture_output=True, text=True, timeout=45,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                lines = result.stdout.strip().splitlines()
                if not lines:
                    raise RuntimeError(result.stderr.strip()[-800:] or "The UV validator returned no result.")
                details = json.loads(lines[-1])
                if result.returncode or not details.get('ok'):
                    raise ValueError(details.get('error', result.stderr[-800:]))
                uv_transfer.assert_unchanged(context, state)
                state['details'] = details
                _UV_TRANSFER_CHECKS[key] = state
                props.uv_transfer_status = (f"T1 PASS: {details['triangles']} triangles, UV '{uv_name}'. "
                                            "T2 visual check pending.")
                print('[MotionSmith Surface] UV transfer:', json.dumps(details), directory)
            else:
                if not state:
                    raise ValueError("Run T1 Validate Transfer first.")
                uv_transfer.assert_unchanged(context, state)
                if context.active_object != state['target']:
                    raise ValueError("Select the original T1 target mesh.")
                if self.action == 'PREVIEW':
                    uv_transfer.preview_checker(context, state)
                    state['checker_accepted'] = False
                    props.uv_transfer_status = "T1 PASS. Compare SOURCE / TRIMESH copies; T2 visual check pending."
                elif self.action == 'ACCEPT':
                    if not state.get('preview_objects'):
                        raise ValueError("Show the checker copies before confirming T2.")
                    state['checker_accepted'] = True
                    props.uv_transfer_status = "T1 PASS; T2 checker visually confirmed by user."
                else:
                    raise ValueError("Unknown UV check action.")
            self.report({'INFO'}, props.uv_transfer_status)
            return {'FINISHED'}
        except Exception as exc:
            props.uv_transfer_status = f"UV check stopped: {exc}"
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


def _finish_job(job, message=None):
    job.done = True
    if hasattr(job._client, "close_progress"):
        job._client.close_progress()
    try:
        if job._timer is not None:
            try:
                job._wm.event_timer_remove(job._timer)
            except (ReferenceError, RuntimeError, ValueError):
                pass
            job._timer = None
    finally:
        try:
            props = job._scene.motionsmith_surface_props
            if props.last_prompt_id == job._prompt_id:
                props.is_generating = False
                if message:
                    props.generation_status = message
        except ReferenceError:
            pass
        _ACTIVE_JOBS.pop(job._prompt_id, None)
        tag_redraw()


def _fetch_history_worker(job):
    try:
        history = job._client.get_history(job._prompt_id)
        job.latest_history = history
    except Exception as exc:
        job.history_error = exc
    finally:
        job.poll_in_flight = False


def _update_progress(job, props, elapsed):
    state = getattr(job._client, "progress", {})
    props.generation_progress = -1.0
    props.generation_remaining = ""
    if state.get("prompt_id") != job._prompt_id:
        props.generation_status = f"Waiting for execution... ({elapsed}s elapsed)"
        if state.get("unavailable"):
            props.generation_status = f"Generating... ({elapsed}s elapsed; live progress unavailable)"
        return
    node = job._prompt_graph.get(state.get("node"), {})
    title = node.get("_meta", {}).get("title", node.get("class_type", "Starting workflow"))
    props.generation_status = f"{title} ({elapsed}s elapsed)"
    total, value = state.get("total", 0), state.get("value", 0)
    if total > 0 and not state.get("unavailable"):
        props.generation_progress = min(1.0, max(0.0, value / total))
        props.generation_status = f"{title}: {value:g}/{total:g} ({elapsed}s elapsed)"
        baseline = state.get("baseline")
        if baseline and value > baseline[0] and value < total:
            per_step = (time.time() - baseline[1]) / (value - baseline[0])
            remaining = max(1, round((total - value) * per_step))
            minutes, seconds = divmod(remaining, 60)
            duration = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
            props.generation_remaining = f"This stage: ~{duration} remaining"
        elif value < total:
            props.generation_remaining = "This stage: estimating remaining time..."
    else:
        props.generation_remaining = "Remaining time unavailable for this stage"


def _poll_job(job):
    """Application timer: completely non-blocking UI using background thread for network queries."""
    if job.done:
        return None
    try:
        if job._scene.motionsmith_surface_props.last_prompt_id != job._prompt_id:
            _finish_job(job)
            return None
        props = job._scene.motionsmith_surface_props

        if hasattr(job, "history_error") and job.history_error:
            err = job.history_error
            job.history_error = None
            raise RuntimeError(str(err))

        history = getattr(job, "latest_history", None)
        if history:
            status = history.get("status", {})
            for kind, details in status.get("messages", []):
                if kind in {"execution_error", "execution_interrupted"}:
                    raise RuntimeError(details.get("exception_message", kind))
            if status.get("completed") or status.get("status_str") == "success":
                try:
                    MOTIONSMITH_SURFACE_OT_generate_texture.apply_result(job, bpy.context, history.get("outputs", {}))
                    _finish_job(job)
                except Exception as exc:
                    _finish_job(job, f"Apply error: {exc}")
                    print(f"[MotionSmith Surface] Completion error applying result: {exc}")
                return None

        # Spawn background network query if not currently in flight
        if not getattr(job, "poll_in_flight", False):
            job.poll_in_flight = True
            t = threading.Thread(target=_fetch_history_worker, args=(job,), daemon=True)
            t.start()

        elapsed = int(time.time() - job._start_time)
        if elapsed > 3600:
            _finish_job(job, "Timed out; use Check / Apply Last Result.")
            return None
        _update_progress(job, props, elapsed)
        tag_redraw()
        return 0.5
    except Exception as exc:
        _finish_job(job, f"Error: {exc}")
        print(f"[MotionSmith Surface] Completion error: {exc}")
        return None


def _job_state(operator, context):
    names = ("_client", "_prompt_id", "_start_time", "_target", "_scene",
             "_prompt_graph", "_uv_mode", "_uv_name", "_comfyui_dir", "_timer")
    values = {name: getattr(operator, name) for name in names}
    if getattr(operator, '_transfer_state', None) is not None:
        values['_transfer_state'] = operator._transfer_state
    return SimpleNamespace(**values, _wm=context.window_manager, done=False,
                           report=lambda levels, message: print(f"[MotionSmith Surface] {message}"))


class MOTIONSMITH_SURFACE_OT_server_start(Operator):
    bl_idname = "motionsmith_surface.server_start"
    bl_label = "Start ComfyUI Server"
    bl_description = "Start the local minimal ComfyUI UltraTex server"

    def execute(self, context):
        prefs = preferences.get_preferences(context)
        fallback_comfy = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "comfyui"))
        comfyui_dir = prefs.comfyui_dir if (prefs and prefs.comfyui_dir and os.path.isdir(prefs.comfyui_dir)) else fallback_comfy
        python_exe = prefs.python_executable if (prefs and prefs.python_executable and os.path.isfile(prefs.python_executable)) else os.path.join(comfyui_dir, ".venv", "Scripts", "python.exe")
        port = prefs.server_port if prefs else 8188
        show_console = prefs.show_console if prefs else True

        props = context.scene.motionsmith_surface_props
        props.server_status = "STARTING"
        props.server_online = False
        tag_redraw()

        success, msg = server_manager.start_server(
            comfyui_dir=comfyui_dir,
            python_exe=python_exe,
            port=port,
            show_console=show_console,
        )

        if success:
            props.server_status = "STARTING"
            props.server_online = False
            self.report({'INFO'}, "ComfyUI server is starting... (ready in ~8 seconds)")
        else:
            props.server_status = "OFFLINE"
            props.server_online = False
            self.report({'WARNING'}, msg)
        tag_redraw()
        return {'FINISHED'}


class MOTIONSMITH_SURFACE_OT_server_stop(Operator):
    bl_idname = "motionsmith_surface.server_stop"
    bl_label = "Stop ComfyUI Server"
    bl_description = "Stop the local ComfyUI server and release port 8188"

    def execute(self, context):
        prefs = preferences.get_preferences(context)
        port = prefs.server_port if prefs else 8188
        props = context.scene.motionsmith_surface_props
        props.server_status = "STOPPING"
        tag_redraw()

        success, msg = server_manager.stop_server(port=port)
        state = server_manager.get_server_state(port)
        props.server_status = state
        props.server_online = (state == "ONLINE")
        tag_redraw()

        if success:
            self.report({'INFO'}, msg)
        else:
            self.report({'WARNING'}, msg)
        return {'FINISHED'}


class MOTIONSMITH_SURFACE_OT_server_status(Operator):
    bl_idname = "motionsmith_surface.server_status"
    bl_label = "Check Server Status"
    bl_description = "Refresh ComfyUI server connection status"

    def execute(self, context):
        prefs = preferences.get_preferences(context)
        port = prefs.server_port if prefs else 8188
        url = prefs.server_url if (prefs and prefs.server_url) else f"http://127.0.0.1:{port}"
        state = server_manager.get_server_state(port=port, url=url)
        props = context.scene.motionsmith_surface_props
        props.server_status = state
        props.server_online = (state == "ONLINE")
        tag_redraw()

        if state == "ONLINE":
            self.report({'INFO'}, f"Server is ONLINE at {url}")
        elif state == "STARTING":
            self.report({'INFO'}, f"Server is STARTING at {url}... (please wait)")
        else:
            self.report({'WARNING'}, f"Server is OFFLINE at {url}")
        return {'FINISHED'}


class MOTIONSMITH_SURFACE_OT_setup_cameras(Operator):
    bl_idname = "motionsmith_surface.setup_cameras"
    bl_label = "Setup Calibrated Cameras"
    bl_description = "Create or align calibrated camera(s) framing the active mesh"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH":
            self.report({'ERROR'}, "Please select a Mesh object in the viewport first.")
            return {'CANCELLED'}

        props = context.scene.motionsmith_surface_props
        cam_mode = camera_utils.get_capture_mode(props)
        cams = camera_utils.setup_calibrated_cameras(context, mode=cam_mode, target_obj=obj)
        tag_redraw()

        if cams:
            self.report({'INFO'}, f"Created/aligned {len(cams)} calibrated camera(s) for '{obj.name}'.")
        else:
            self.report({'WARNING'}, "Could not set up cameras for the selected object.")
        return {'FINISHED'}


class MOTIONSMITH_SURFACE_OT_view_camera(Operator):
    bl_idname = "motionsmith_surface.view_camera"
    bl_label = "View Camera"
    bl_description = "Switch 3D Viewport to the selected or active calibrated camera view"

    camera_name: StringProperty(
        name="Camera Name",
        description="Optional camera name to switch to directly",
        default="",
    )

    def execute(self, context):
        target_cam = None

        # 1. If camera_name is explicitly specified, find that camera object
        if self.camera_name and self.camera_name in context.scene.objects:
            obj = context.scene.objects[self.camera_name]
            if obj.type == 'CAMERA':
                target_cam = obj

        # 2. Check if user currently has a camera object selected (active object or in selected_objects)
        if not target_cam:
            if context.active_object and context.active_object.type == 'CAMERA':
                target_cam = context.active_object
            else:
                for obj in context.selected_objects:
                    if obj.type == 'CAMERA':
                        target_cam = obj
                        break

        # 3. Fallback to active scene camera
        if not target_cam and context.scene.camera:
            target_cam = context.scene.camera

        # 4. Fallback to any MS_Cam in scene
        if not target_cam:
            for obj in context.scene.objects:
                if obj.type == 'CAMERA' and obj.name.startswith("MS_Cam"):
                    target_cam = obj
                    break

        # 5. Fallback: Setup cameras if none exist
        if not target_cam:
            props = context.scene.motionsmith_surface_props
            cam_mode = camera_utils.get_capture_mode(props)
            cams = camera_utils.setup_calibrated_cameras(context, mode=cam_mode)
            if cams:
                target_cam = cams[0]

        if not target_cam:
            self.report({'WARNING'}, "No camera found in scene. Click 'Setup Cameras' first.")
            return {'CANCELLED'}

        # Assign as active scene camera
        context.scene.camera = target_cam

        # Enforce 1:1 square render resolution in Blender scene
        props = getattr(context.scene, "motionsmith_surface_props", None)
        res = int(props.view_resolution) if (props and hasattr(props, "view_resolution")) else 1024
        context.scene.render.resolution_x = res
        context.scene.render.resolution_y = res
        context.scene.render.resolution_percentage = 100
        context.scene.render.pixel_aspect_x = 1.0
        context.scene.render.pixel_aspect_y = 1.0

        # Switch 3D Viewport(s) to CAMERA perspective
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        if space.use_local_camera:
                            space.camera = target_cam
                        space.region_3d.view_perspective = 'CAMERA'

        tag_redraw()
        self.report({'INFO'}, f"Active view set to camera '{target_cam.name}'.")
        return {'FINISHED'}


class MOTIONSMITH_SURFACE_OT_refresh_models(Operator):
    bl_idname = "motionsmith_surface.refresh_models"
    bl_label = "Refresh Models"
    bl_description = "Rescan models folder for new checkpoints, LoRAs, and VAEs"

    def execute(self, context):
        model_catalog.refresh_catalog()
        tag_redraw()
        self.report({'INFO'}, "Model catalog refreshed.")
        return {'FINISHED'}


class MOTIONSMITH_SURFACE_OT_generate_texture(Operator):
    bl_idname = "motionsmith_surface.generate_texture"
    bl_label = "Generate UltraTex PBR Texture"
    bl_description = "Capture the target and apply the selected workflow's baked textures and UVs"

    _timer = None
    _client = None
    _prompt_id = ""
    _start_time = 0.0
    _target = None
    _scene = None
    _prompt_graph = None
    _uv_mode = ""
    _uv_name = ""
    _comfyui_dir = ""

    _job = None

    def cancel_timer(self, context):
        if self._job is not None:
            _finish_job(self._job)
            return
        try:
            if self._timer is not None:
                try:
                    context.window_manager.event_timer_remove(self._timer)
                except (ReferenceError, RuntimeError, ValueError):
                    pass
                self._timer = None
        finally:
            if self._scene:
                self._scene.motionsmith_surface_props.is_generating = False
            c_client = getattr(self, "_client", None)
            if c_client and hasattr(c_client, "close_progress"):
                c_client.close_progress()

    def modal(self, context, event):
        job = self._job
        if job is None or job.done:
            return {'FINISHED'}
        if event.type == 'ESC':
            try:
                cancelled = job._client.cancel_prompt(job._prompt_id)
                message = "Cancelled by user." if cancelled else "Stopped waiting; use Check / Apply Last Result."
            except Exception as exc:
                message = f"Cancel failed: {exc}"
            _finish_job(job, message)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}

    def cancel(self, context):
        self.cancel_timer(context)

    def apply_result(self, context, outputs):
        obj = self._target
        if any(node.get('class_type') == 'Hy3DBakeFromMultiview' for node in self._prompt_graph.values()):
            metadata = next((node.get('_meta', {}).get('surface_transfer')
                             for node in self._prompt_graph.values()
                             if node.get('class_type') == 'SaveImage'
                             and node.get('_meta', {}).get('surface_transfer')), None)
            state = getattr(self, '_transfer_state', None) or _UV_TRANSFER_CHECKS.get(self._scene.as_pointer())
            if not state or not metadata or any(state.get(key) != metadata.get(key)
                                                for key in ('directory', 'fingerprint', 'uv_name', 'glb_hash')):
                raise ValueError("The original transfer snapshot is unavailable. Rerun T1/T2 and regenerate.")
            if obj != state['target'] or not state.get('checker_accepted'):
                raise ValueError("The original mesh and its confirmed T2 check are required.")
            uv_transfer.assert_unchanged(context, state)
            uv_transfer.assert_input_unchanged(state)
            if obj.data.users > 1 or len(obj.material_slots) > 1:
                raise ValueError("Mesh painting requires a single material slot and unshared mesh data.")
            files = self._client.resolve_bake_outputs(outputs, self._prompt_graph, self._comfyui_dir)
            material_utils.apply_pbr_textures(
                obj, files['albedo'], material_name=f"M_Surface_BaseColor_{self._prompt_id[:12]}",
                uv_name=state['uv_name'], slot_policy='ACTIVE_SLOT',
                normal_path=files.get('normal'), roughness_path=files.get('roughness'),
                metallic_path=files.get('metallic'), height_path=files.get('height'))
            material_utils.set_viewport_material_shading(context)
            self._scene.motionsmith_surface_props.generation_status = f"Baked textures applied to {obj.name}"
            self.report({'INFO'}, f"Baked textures applied to {obj.name}; original UV preserved.")
            return
        if any(node.get("class_type") == "ChordMaterialEstimation" for node in self._prompt_graph.values()):
            files = self._client.resolve_bake_outputs(outputs, self._prompt_graph, self._comfyui_dir)
            # Restore direct image-to-material application. Old Flux-only results
            # remain standalone: a character picture is not a UV texture atlas.
            target = obj if not any(n.get('class_type') == 'KSampler'
                                    for n in self._prompt_graph.values()) else None
            if target is not None:
                if self._scene.objects.get(target.name) != target:
                    raise ValueError('The original target mesh is no longer in the scene.')
                if self._uv_name not in target.data.uv_layers:
                    raise ValueError('The original target UV map no longer exists.')
            mat = material_utils.apply_pbr_textures(
                target, files["albedo"], material_name=f"M_Chord_{self._prompt_id[:12]}",
                uv_name=self._uv_name, roughness_path=files["roughness"],
                metallic_path=files["metallic"], normal_path=files["normal"],
                height_path=files["height"], create_only=target is None,
                slot_policy="ACTIVE_SLOT")
            if target is not None:
                material_utils.set_viewport_material_shading(context)
            message = f"Applied PBR material to {target.name}" if target else f"Created {mat.name}"
            self._scene.motionsmith_surface_props.generation_status = message
            self.report({'INFO'}, message)
            return
        if obj is None or obj.name not in self._scene.objects:
            raise ValueError("The target mesh was removed from the scene.")
        files = self._client.resolve_bake_outputs(outputs, self._prompt_graph, self._comfyui_dir)
        if self._uv_mode == "keep_existing":
            if self._uv_name not in obj.data.uv_layers:
                raise ValueError("The target no longer has its exported UV map.")
            uv_name = self._uv_name
        else:
            uv_name = material_utils.apply_baked_uvs(context, obj, files["glb"])
        props = self._scene.motionsmith_surface_props
        material_utils.apply_pbr_textures(
            obj, files["albedo"], files.get("orm"),
            material_name=f"M_UltraTex_{obj.name}", uv_name=uv_name,
            roughness_path=files.get("roughness"), metallic_path=files.get("metallic"),
            normal_path=files.get("normal"),
            slot_policy=getattr(props, "material_apply_mode", "ALL_SLOTS"))
        material_utils.set_viewport_material_shading(context)
        props.generation_status = f"Applied to {obj.name}"
        self.report({'INFO'}, f"UltraTex textures and UVs applied to {obj.name}.")

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH" or obj.mode != 'OBJECT':
            self.report({'ERROR'}, "Select a mesh in Object Mode.")
            return {'CANCELLED'}
        props = context.scene.motionsmith_surface_props
        if props.is_generating:
            self.report({'WARNING'}, "A texture generation is already running.")
            return {'CANCELLED'}
        if not obj.data.polygons:
            self.report({'ERROR'}, "The target mesh has no faces.")
            return {'CANCELLED'}
        if props.uv_mode == "keep_existing" and not obj.data.uv_layers.active:
            self.report({'ERROR'}, "Keep Existing UVs requires a UV map. Select Comfy GPU or Xatlas.")
            return {'CANCELLED'}
        if props.uv_mode != "keep_existing" and any(m.show_viewport for m in obj.modifiers):
            self.report({'ERROR'}, "Generated UVs require the exported geometry to match the mesh. Use Keep Existing UVs or apply the target modifiers first.")
            return {'CANCELLED'}

        prefs = preferences.get_preferences(context)
        comfyui_dir = preferences.get_comfyui_dir(context)
        server_url = prefs.server_url if prefs else "http://127.0.0.1:8188"
        c_client = client.ComfyUIClient(server_url)
        if not c_client.is_connected():
            self.report({'ERROR'}, f"Start ComfyUI at {server_url} first.")
            return {'CANCELLED'}

        input_mode = "BOTH" if props.texture_quality == "MANUAL_10_VIEWS" else props.input_mode
        if props.texture_quality != "MANUAL_10_VIEWS" and input_mode == "BOTH" and not props.positive_prompt.strip():
            input_mode = "IMAGE"
        if props.texture_quality != "MANUAL_10_VIEWS" and input_mode == "PROMPT" and not props.positive_prompt.strip():
            self.report({'ERROR'}, "Enter a positive prompt or select Image Only.")
            return {'CANCELLED'}
        selected = list(context.selected_objects)
        active = context.view_layer.objects.active
        try:
            props.is_generating = True
            props.generation_progress = -1.0
            props.generation_remaining = ""
            self._scene = context.scene
            if props.texture_quality == "LOW_VRAM_GGUF":
                input_dir = os.path.join(comfyui_dir, "input", "3d", "MotionSmith_Surface")
            else:
                input_dir = os.path.join(comfyui_dir, "input", "MotionSmith_Surface")
            os.makedirs(input_dir, exist_ok=True)
            # Each run has its own inputs, so cached LoadImage nodes cannot reuse a previous capture.
            run_id = uuid.uuid4().hex[:12]
            run_dir = os.path.join(input_dir, run_id)
            os.makedirs(run_dir, exist_ok=True)
            mesh_path = os.path.join(run_dir, "target.obj")
            self._uv_name = obj.data.uv_layers.active.name if obj.data.uv_layers.active else ""
            for item in context.selected_objects:
                item.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            original_render_uv = next((layer for layer in obj.data.uv_layers if layer.active_render), None)
            try:
                if self._uv_name:
                    obj.data.uv_layers[self._uv_name].active_render = True
                bpy.ops.wm.obj_export(
                    filepath=mesh_path, export_selected_objects=True,
                    export_materials=False, export_triangulated_mesh=True,
                    forward_axis='NEGATIVE_Z', up_axis='Y',
                    apply_modifiers=True, export_eval_mode='DAG_EVAL_VIEWPORT')
            finally:
                if original_render_uv:
                    original_render_uv.active_render = True
            names = []
            reference_is_render = True
            if input_mode != "PROMPT":
                if props.texture_quality == "MANUAL_10_VIEWS":
                    if props.manual_source == "CAMERAS":
                        props.generation_status = "Capturing 10 calibrated camera views..."
                        tag_redraw()
                        captures = camera_utils.render_calibrated_views(
                            context, run_dir, mode="MANUAL_10",
                            resolution=int(props.view_resolution), target_obj=obj)
                        if not captures or len(captures) != 10:
                            raise ValueError(f"Expected 10 camera captures, got {len(captures) if captures else 0}")
                        names = [os.path.relpath(os.path.join(run_dir, os.path.basename(name)),
                                                os.path.join(comfyui_dir, "input")).replace(os.sep, "/")
                                 for name in captures]
                        reference_is_render = True
                    elif props.manual_source == "FOLDER":
                        folder = os.path.abspath(bpy.path.abspath(props.manual_images_dir.strip()))
                        matched_paths = camera_utils.find_10_views_in_folder(folder)
                        collected = []
                        for idx, (source_path, vname) in enumerate(zip(matched_paths, camera_utils.MANUAL_VIEW_NAMES)):
                            dst = os.path.join(run_dir, f"view_{idx}_{vname}" + os.path.splitext(source_path)[1])
                            shutil.copyfile(source_path, dst)
                            collected.append(dst)
                        names = [os.path.relpath(p, os.path.join(comfyui_dir, "input")).replace(os.sep, "/") for p in collected]
                        reference_is_render = False
                    else:  # FILES
                        view_props = [
                            props.manual_image_0_front, props.manual_image_1_left, props.manual_image_2_back,
                            props.manual_image_3_right, props.manual_image_4_top, props.manual_image_5_bottom,
                            props.manual_image_6_front_left, props.manual_image_7_back_left,
                            props.manual_image_8_back_right, props.manual_image_9_front_right,
                        ]
                        collected = []
                        for idx, (p_val, vname) in enumerate(zip(view_props, camera_utils.MANUAL_VIEW_NAMES)):
                            source_path = os.path.abspath(bpy.path.abspath(p_val.strip()))
                            if not os.path.isfile(source_path):
                                raise FileNotFoundError(f"Missing file for view {idx} ({vname}): {source_path}")
                            dst = os.path.join(run_dir, f"view_{idx}_{vname}" + os.path.splitext(source_path)[1])
                            shutil.copyfile(source_path, dst)
                            collected.append(dst)
                        names = [os.path.relpath(p, os.path.join(comfyui_dir, "input")).replace(os.sep, "/") for p in collected]
                        reference_is_render = False
                else:
                    custom_reference = props.custom_reference_image.strip()
                    if custom_reference:
                        source = os.path.abspath(bpy.path.abspath(custom_reference))
                        if not os.path.isfile(source):
                            raise FileNotFoundError(f"Reference image not found: {source}")
                        reference = os.path.join(run_dir, "reference" + os.path.splitext(source)[1])
                        shutil.copyfile(source, reference)
                        names = [os.path.relpath(reference, os.path.join(comfyui_dir, "input")).replace(os.sep, "/")]
                        reference_is_render = False
                    else:
                        props.generation_status = "Capturing calibrated camera views..."
                        tag_redraw()
                        captures = camera_utils.render_calibrated_views(
                            context, run_dir, mode=camera_utils.get_capture_mode(props),
                            resolution=int(props.view_resolution), target_obj=obj)
                        if not captures:
                            raise ValueError("No camera captures were produced.")
                        names = [os.path.relpath(os.path.join(run_dir, os.path.basename(name)),
                                                os.path.join(comfyui_dir, "input")).replace(os.sep, "/")
                                 for name in captures]
            settings = dict(
                input_mode=input_mode,
                reference_is_render=reference_is_render,
                remove_reference_background=props.remove_reference_background,
                positive_prompt=props.positive_prompt, negative_prompt=props.negative_prompt,
                unet_name=props.unet_model, clip_name=props.clip_model,
                vae_name=props.vae_model, decoder_name=props.decoder_model,
                lora_albedo_name=props.lora_albedo_model, lora_mr_name=props.lora_mr_model,
                bg_removal_name=props.bg_removal_model, steps=props.steps, guidance=props.guidance,
                view_resolution=int(props.view_resolution), texture_size=int(props.texture_size),
                seed=props.seed, uv_mode=props.uv_mode,
                reference_alignment=props.reference_alignment,
                multiview_denoise=props.multiview_denoise,
                lora_albedo_strength=props.lora_albedo_strength,
                lora_mr_strength=props.lora_mr_strength,
                view_weight_power=props.view_weight_power, best_view_mix=props.best_view_mix,
                edge_feather_px=props.edge_feather_px,
                output_prefix=f"UltraTex/{run_id}/surface")
            for name in ("render_size", "drop_background_tokens", "memory_factor", "attention",
                         "sparse_topk", "token_chunk", "albedo_denoise", "mr_resolution",
                         "mr_steps", "enable_mr", "use_negative_prompt", "keep_above", "keep_feather",
                         "view_count", "extra_steps", "extra_angle_mode", "tiled_decode",
                         "fill_unseen", "blend_mode", "repair_mode", "uv_padding"):
                if hasattr(props, name):
                    settings[name] = getattr(props, name)
            settings["render_size"] = int(settings.get("render_size", props.view_resolution))
            settings["mr_resolution"] = int(settings.get("mr_resolution", props.view_resolution))
            prompt = workflow.build_workflow_prompt(
                props.texture_quality, mesh_path, names,
                workflow_dir=os.path.join(comfyui_dir, "user", "default", "workflows", "PixelArtistry"),
                **settings)
            # Reject missing selected model files before queueing (Loaders used by this graph only).
            c_client.validate_local_models(prompt, comfyui_dir)
            success, prompt_id, response = c_client.queue_prompt(prompt)
            if not success:
                raise ValueError(prompt_id)
            self._client, self._prompt_id, self._prompt_graph = c_client, prompt_id, prompt
            self._target, self._comfyui_dir, self._uv_mode = obj, comfyui_dir, props.uv_mode
            self._start_time = time.time()
            props.last_prompt_id = prompt_id
            props.last_target_name = obj.name
            props.generation_status = "Inference started..."
            if bpy.app.background:
                success, message, outputs = c_client.poll_execution(prompt_id, timeout=3600, interval=1)
                if not success:
                    raise RuntimeError(message)
                self.apply_result(context, outputs)
                self.cancel_timer(context)
                return {'FINISHED'}
            self._timer = context.window_manager.event_timer_add(1.0, window=context.window)
            self._job = _job_state(self, context)
            _ACTIVE_JOBS[prompt_id] = self._job
            job = self._job
            job.poll_callback = lambda: _poll_job(job)
            bpy.app.timers.register(job.poll_callback, first_interval=1.0)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            props.generation_status = f"Error: {exc}"
            self.cancel_timer(context)
            props.is_generating = False
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        finally:
            for item in context.selected_objects:
                item.select_set(False)
            for item in selected:
                if item.name in context.view_layer.objects:
                    item.select_set(True)
            context.view_layer.objects.active = active


class MOTIONSMITH_SURFACE_OT_generate_material(Operator):
    bl_idname = "motionsmith_surface.generate_material"
    bl_label = "Generate PBR Material"
    bl_description = "Create material maps from an existing texture image and use the selected mesh's existing UVs"

    # Registered Blender operators must not inherit another registered operator:
    # registering the child replaces the parent's RNA Python class association.
    _job = None
    _timer = None
    _scene = None
    cancel_timer = MOTIONSMITH_SURFACE_OT_generate_texture.cancel_timer
    modal = MOTIONSMITH_SURFACE_OT_generate_texture.modal
    cancel = MOTIONSMITH_SURFACE_OT_generate_texture.cancel
    apply_result = MOTIONSMITH_SURFACE_OT_generate_texture.apply_result

    def execute(self, context):
        props = context.scene.motionsmith_surface_props
        if props.is_generating:
            self.report({'WARNING'}, "A texture generation is already running.")
            return {'CANCELLED'}
        image_path = bpy.path.abspath(props.pbr_image.strip())
        if not props.pbr_image.strip() or not os.path.isfile(image_path):
            self.report({'ERROR'}, "Select an existing image file.")
            return {'CANCELLED'}
        try:
            prefs = preferences.get_preferences(context)
            comfyui_dir = preferences.get_comfyui_dir(context)
            c_client = client.ComfyUIClient(prefs.server_url if prefs else "http://127.0.0.1:8188")
            if not c_client.is_connected():
                raise RuntimeError("Start ComfyUI first.")
            run_id = uuid.uuid4().hex[:12]
            self._transfer_state = None
            import json
            import urllib.request
            with urllib.request.urlopen(f'{c_client.server_url}/object_info/ChordLoadModel', timeout=5) as response:
                info = json.load(response)
            field = info.get('ChordLoadModel', {}).get('input', {}).get('required', {}).get('ckpt_name', [[]])
            choices = (field[1].get('options', []) if field[0] == 'COMBO' and len(field) > 1
                       else field[0] if isinstance(field[0], list) else [])
            selected = props.pbr_checkpoint.replace('\\', '/')
            checkpoint = next((name for name in choices if name.replace('\\', '/') == selected), None)
            if not checkpoint:
                raise FileNotFoundError('The selected Chord model is unavailable on the server.')
            run_dir = os.path.join(comfyui_dir, 'input', 'MotionSmith_Surface', run_id)
            input_name = 'material' + os.path.splitext(image_path)[1]
            prompt = workflow.build_material_prompt(
                f'MotionSmith_Surface/{run_id}/{input_name}', checkpoint, f'Chord/{run_id}')
            c_client.validate_local_models(prompt, comfyui_dir)
            os.makedirs(run_dir, exist_ok=True)
            shutil.copy2(image_path, os.path.join(run_dir, input_name))
            obj = context.active_object
            target = obj if (obj and obj.type == 'MESH' and obj.mode == 'OBJECT'
                             and obj.data.polygons and obj.data.uv_layers.active) else None
            success, prompt_id, response = c_client.queue_prompt(prompt)
            if not success:
                raise RuntimeError(prompt_id)
            self._scene, self._target = context.scene, target
            self._client, self._prompt_id, self._prompt_graph = c_client, prompt_id, prompt
            self._uv_mode = "keep_existing"
            self._uv_name = target.data.uv_layers.active.name if target else ''
            self._comfyui_dir, self._start_time = comfyui_dir, time.time()
            props.last_prompt_id, props.last_target_name = prompt_id, target.name if target else ""
            props.is_generating = True
            props.generation_progress = -1.0
            props.generation_remaining = ""
            props.generation_status = 'Generating PBR material maps from image...'
            if bpy.app.background:
                success, message, outputs = c_client.poll_execution(prompt_id, timeout=3600, interval=1)
                if not success:
                    raise RuntimeError(message)
                self.apply_result(context, outputs)
                props.is_generating = False
                return {'FINISHED'}
            self._timer = context.window_manager.event_timer_add(1.0, window=context.window)
            self._job = _job_state(self, context)
            _ACTIVE_JOBS[prompt_id] = self._job
            job = self._job
            job.poll_callback = lambda: _poll_job(job)
            bpy.app.timers.register(job.poll_callback, first_interval=1.0)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            props.is_generating = False
            props.generation_status = f"Error: {exc}"
            self.cancel_timer(context)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class MOTIONSMITH_SURFACE_OT_cancel_generation(Operator):
    bl_idname = "motionsmith_surface.cancel_generation"
    bl_label = "Cancel"
    bl_description = "Cancel this generation in ComfyUI and stop applying its result"

    @classmethod
    def poll(cls, context):
        props = context.scene.motionsmith_surface_props
        return props.is_generating and bool(props.last_prompt_id)

    def execute(self, context):
        props = context.scene.motionsmith_surface_props
        job = _ACTIVE_JOBS.get(props.last_prompt_id)
        try:
            prefs = preferences.get_preferences(context)
            c_client = job._client if job else client.ComfyUIClient(
                prefs.server_url if prefs else "http://127.0.0.1:8188")
            if not c_client.cancel_prompt(props.last_prompt_id):
                props.generation_status = "Cancel not confirmed; use Check / Apply Last Result."
                self.report({'WARNING'}, props.generation_status)
                tag_redraw()
                return {'CANCELLED'}
        except Exception as exc:
            self.report({'WARNING'}, f"Cancel failed: {exc}")
            return {'CANCELLED'}
        if job:
            _finish_job(job, "Cancelled by user.")
        else:
            props.is_generating = False
            props.generation_status = "Cancelled by user."
            tag_redraw()
        return {'FINISHED'}


class MOTIONSMITH_SURFACE_OT_recover_result(Operator):
    bl_idname = "motionsmith_surface.recover_result"
    bl_label = "Check / Apply Last Result"
    bl_description = "Recover the last completed result onto the selected mesh without generating again"

    def execute(self, context):
        props = context.scene.motionsmith_surface_props
        if not props.last_prompt_id:
            self.report({'WARNING'}, "No previous prompt is recorded in this scene.")
            return {'CANCELLED'}
        prefs = preferences.get_preferences(context)
        c_client = client.ComfyUIClient(prefs.server_url if prefs else "http://127.0.0.1:8188")
        history = c_client.get_history(props.last_prompt_id)
        if not history:
            queue = c_client.get_queue()
            if queue is None:
                self.report({'ERROR'}, "Cannot reach ComfyUI. The generation state was preserved.")
                return {'CANCELLED'}
            if any(item[1] == props.last_prompt_id for key in ("queue_running", "queue_pending") for item in queue.get(key, [])):
                self.report({'INFO'}, "This prompt is still running or queued.")
                return {'FINISHED'}
            props.is_generating = False
            props.generation_status = "Job not found in server history. Controls unlocked."
            tag_redraw()
            return {'FINISHED'}
        status = history.get("status", {})
        if not (status.get("completed") or status.get("status_str") in {"success", "error"}):
            self.report({'INFO'}, "This prompt has not finished.")
            return {'FINISHED'}
        existing = _ACTIVE_JOBS.get(props.last_prompt_id)
        if existing:
            _finish_job(existing)
        try:
            if status.get("status_str") == "error":
                raise RuntimeError("ComfyUI reports an execution error; see the server log.")
            prompt_graph = history["prompt"][2] if (len(history.get("prompt", [])) > 2) else {}
            chord = any(n.get("class_type") == "ChordMaterialEstimation" for n in prompt_graph.values())
            # Ensure the original target mesh is safely targeted
            if chord and not props.last_target_name:
                obj = None
            elif props.last_target_name and props.last_target_name in context.scene.objects:
                obj = context.scene.objects[props.last_target_name]
                context.view_layer.objects.active = obj
                obj.select_set(True)
            else:
                obj = context.active_object
                if not obj or obj.type != "MESH":
                    raise ValueError("Select the original target mesh to apply its completed result.")
                if props.last_target_name and obj.name != props.last_target_name:
                    raise ValueError(
                        f"Active mesh '{obj.name}' does not match original target '{props.last_target_name}'. "
                        f"Please select '{props.last_target_name}' to recover this bake."
                    )

            # Retrieve exact generation-time uv_mode from the prompt graph
            rec_uv_mode = props.uv_mode
            for _, n in prompt_graph.items():
                if isinstance(n, dict) and n.get("class_type") in {"UltraTexPrep", "UTXUnwrapMeshUVV25"}:
                    rec_uv_mode = n.get("inputs", {}).get("uv_mode", rec_uv_mode)
                    break

            job = SimpleNamespace(
                _client=c_client, _prompt_id=props.last_prompt_id,
                _target=obj, _scene=context.scene, _prompt_graph=prompt_graph,
                _uv_mode=rec_uv_mode, _uv_name=(obj.data.uv_layers.active.name if obj and obj.data.uv_layers.active else ""),
                _comfyui_dir=preferences.get_comfyui_dir(context),
                report=self.report)
            MOTIONSMITH_SURFACE_OT_generate_texture.apply_result(job, context, history.get("outputs", {}))
            return {'FINISHED'}
        except Exception as exc:
            props.generation_status = f"Recovery failed: {exc}"
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        finally:
            props.is_generating = False
            tag_redraw()


classes = (
    MOTIONSMITH_SURFACE_OT_uv_transfer_check,
    MOTIONSMITH_SURFACE_OT_server_start,
    MOTIONSMITH_SURFACE_OT_server_stop,
    MOTIONSMITH_SURFACE_OT_server_status,
    MOTIONSMITH_SURFACE_OT_setup_cameras,
    MOTIONSMITH_SURFACE_OT_view_camera,
    MOTIONSMITH_SURFACE_OT_refresh_models,
    MOTIONSMITH_SURFACE_OT_generate_texture,
    MOTIONSMITH_SURFACE_OT_generate_material,
    MOTIONSMITH_SURFACE_OT_cancel_generation,
    MOTIONSMITH_SURFACE_OT_recover_result,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for state in _UV_TRANSFER_CHECKS.values():
        uv_transfer.clear_preview(state)
    _UV_TRANSFER_CHECKS.clear()
    for job in list(_ACTIVE_JOBS.values()):
        _finish_job(job)
        if bpy.app.timers.is_registered(job.poll_callback):
            bpy.app.timers.unregister(job.poll_callback)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
