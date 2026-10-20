"""Offline mesh/UV transport checks. No ComfyUI server or AI models are used."""

import hashlib
import itertools
import json
import os
import struct

import numpy as np


def _corners(mesh, uv_name, matrix):
    mesh.calc_loop_triangles()
    positions = np.array([v.co[:] for v in mesh.vertices], dtype=np.float64)
    transform = np.array(matrix, dtype=np.float64)
    positions = positions @ transform[:3, :3].T + transform[:3, 3]
    indices = np.array([t.vertices[:] for t in mesh.loop_triangles], dtype=np.int64)
    loops = np.array([t.loops[:] for t in mesh.loop_triangles], dtype=np.int64)
    uv = np.array([item.uv[:] for item in mesh.uv_layers[uv_name].data], dtype=np.float64)
    return positions[indices], uv[loops]


def _evaluated(context, obj, uv_name):
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        if uv_name not in mesh.uv_layers:
            raise ValueError("The evaluated mesh has lost the selected UV map.")
        return _corners(mesh, uv_name, evaluated.matrix_world)
    finally:
        evaluated.to_mesh_clear()


def fingerprint(context, obj, uv_name):
    """Include original topology/all UVs and the evaluated surface/world transform."""
    if obj.mode != 'OBJECT' or obj.type != 'MESH':
        raise ValueError("The target must remain a mesh in Object Mode.")
    digest = hashlib.sha256()
    def update_array(values):
        array = np.asarray(values)
        digest.update(repr((array.shape, array.dtype.str)).encode('ascii'))
        digest.update(array.tobytes())

    for values in (
        [v.co[:] for v in obj.data.vertices],
        [e.vertices[:] for e in obj.data.edges],
        [loop.vertex_index for loop in obj.data.loops],
        [(p.loop_start, p.loop_total) for p in obj.data.polygons],
        np.array(obj.matrix_world),
    ):
        update_array(values)
    for layer in obj.data.uv_layers:
        digest.update(json.dumps(layer.name).encode('utf-8'))
        update_array(np.asarray([v.uv[:] for v in layer.data], dtype=np.float64))
    for values in _evaluated(context, obj, uv_name):
        update_array(values)
    return digest.hexdigest()


def assert_unchanged(context, state):
    obj = state['target']
    try:
        if (obj.as_pointer() != state['object_pointer'] or obj.data.as_pointer() != state['mesh_pointer']
                or context.scene.objects.get(obj.name) != obj
                or fingerprint(context, obj, state['uv_name']) != state['fingerprint']):
            raise ValueError("Target geometry or UV data changed. Run T1 again; no checker was applied.")
    except ReferenceError:
        raise ValueError("The original target no longer exists. Run T1 again.") from None


def assert_input_unchanged(state):
    path = os.path.join(state['directory'], 'target.glb')
    with open(path, 'rb') as handle:
        actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    if actual != state.get('glb_hash'):
        raise ValueError("The validated GLB changed or its snapshot is unavailable. Run T1/T2 again.")


def export_snapshot(context, obj, uv_name, directory):
    """Export only a triangulated, single-UV temporary copy; never edit the target."""
    import bpy
    if obj.type != 'MESH' or obj.mode != 'OBJECT' or not obj.data.polygons:
        raise ValueError("Select a mesh with faces in Object Mode.")
    if len(obj.material_slots) > 1:
        raise ValueError("T1 currently supports a single material slot only.")
    if uv_name not in obj.data.uv_layers:
        raise ValueError("Select the target UV map.")
    before = fingerprint(context, obj, uv_name)
    positions, uv = _evaluated(context, obj, uv_name)
    if not np.isfinite(positions).all() or not np.isfinite(uv).all():
        raise ValueError("Mesh positions and UV coordinates must be finite.")
    if (uv < -1e-6).any() or (uv > 1.0 + 1e-6).any():
        raise ValueError("T1 currently supports a single 0–1 UV atlas; UDIM is not supported.")
    os.makedirs(directory, exist_ok=True)
    state = dict(target=obj, object_pointer=obj.as_pointer(), mesh_pointer=obj.data.as_pointer(),
                 uv_name=uv_name, fingerprint=before, directory=directory)
    # World-space triangles are the exact export geometry, independent of modifiers and seams.
    temporary_mesh = bpy.data.meshes.new("MS_UV_Transfer_Export")
    temporary_obj = bpy.data.objects.new("MS_UV_Transfer_Export", temporary_mesh)
    temporary_material = bpy.data.materials.new("MS_UV_Transfer_Neutral")
    selected, active = list(context.selected_objects), context.view_layer.objects.active
    try:
        temporary_mesh.from_pydata(positions.reshape(-1, 3).tolist(), [],
                                  np.arange(len(positions) * 3).reshape(-1, 3).tolist())
        layer = temporary_mesh.uv_layers.new(name=uv_name)
        layer.data.foreach_set('uv', uv.reshape(-1))
        temporary_mesh.uv_layers.active_index = 0
        layer.active_render = True
        # Trimesh 4.12 only attaches TEXCOORD_0 when the primitive has a material.
        # A fresh constant material carries no source textures or extra UV sets.
        temporary_mesh.materials.append(temporary_material)
        context.scene.collection.objects.link(temporary_obj)
        for item in selected:
            item.select_set(False)
        temporary_obj.select_set(True)
        context.view_layer.objects.active = temporary_obj
        result = bpy.ops.export_scene.gltf(
            filepath=os.path.join(directory, 'target.glb'), export_format='GLB',
            use_selection=True, export_texcoords=True, export_normals=True,
            export_materials='VIEWPORT', export_yup=True, export_apply=False,
            export_animations=False, export_skins=False, export_morph=False,
        )
        if 'FINISHED' not in result:
            raise RuntimeError("GLB export did not finish.")
    finally:
        bpy.data.objects.remove(temporary_obj, do_unlink=True)
        bpy.data.meshes.remove(temporary_mesh)
        bpy.data.materials.remove(temporary_material)
        for item in selected:
            item.select_set(True)
        context.view_layer.objects.active = active
    assert_unchanged(context, state)
    # Blender Z-up -> glTF Y-up. Expected UVs are after Trimesh's glTF V conversion.
    gltf_positions = positions[..., [0, 2, 1]].copy()
    gltf_positions[..., 2] *= -1
    np.savez(os.path.join(directory, 'source.npz'), positions=gltf_positions, uv=uv)
    with open(os.path.join(directory, 'target.glb'), 'rb') as handle:
        state['glb_hash'] = hashlib.file_digest(handle, 'sha256').hexdigest()
    return state


def compare_corners(expected_positions, expected_uv, actual_positions, actual_uv):
    """Match oriented triangle corners without assuming vertex or face order."""
    from scipy.spatial import cKDTree
    ep, eu = np.asarray(expected_positions), np.asarray(expected_uv)
    ap, au = np.asarray(actual_positions), np.asarray(actual_uv)
    if (ep.shape != ap.shape or eu.shape != au.shape or ep.ndim != 3
            or ep.shape[1:] != (3, 3) or eu.shape != ep.shape[:2] + (2,) or not len(ep)):
        raise ValueError("Triangle count or corner data shape changed during GLB loading.")
    if not all(np.isfinite(a).all() for a in (ep, eu, ap, au)):
        raise ValueError("Non-finite geometry or UV data.")
    position_tolerance = max(float(np.ptp(ep.reshape(-1, 3), axis=0).max()) * 1e-6,
                             float(np.abs(ep).max()) * np.finfo(np.float32).eps * 4, 1e-7)
    uv_tolerance = 1e-6
    tree = cKDTree(ap.mean(axis=1))
    used, max_position_error, max_uv_error = set(), 0.0, 0.0
    for index, (points, texcoords) in enumerate(zip(ep, eu)):
        match = None
        for candidate in tree.query_ball_point(points.mean(axis=0), position_tolerance):
            if candidate in used:
                continue
            for order in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
                error = float(np.linalg.norm(points - ap[candidate, order, :], axis=1).max())
                uv_error = float(np.abs(texcoords - au[candidate, order, :]).max())
                if error <= position_tolerance and uv_error <= uv_tolerance:
                    match = candidate, error, uv_error
                    break
            if match:
                break
        if match is None:
            raise ValueError(f"Position/UV/winding mismatch at source triangle {index}.")
        used.add(match[0])
        max_position_error = max(max_position_error, match[1])
        max_uv_error = max(max_uv_error, match[2])
    return dict(triangles=len(ep), max_position_error=max_position_error,
                max_uv_error=max_uv_error, position_tolerance=position_tolerance,
                uv_tolerance=uv_tolerance)


def _glb_contract(path):
    with open(path, 'rb') as handle:
        magic, version, _ = struct.unpack('<4sII', handle.read(12))
        length, kind = struct.unpack('<II', handle.read(8))
        if magic != b'glTF' or version != 2 or kind != 0x4E4F534A:
            raise ValueError("Expected a GLB 2.0 JSON chunk.")
        document = json.loads(handle.read(length))
    meshes = document.get('meshes', [])
    if len(meshes) != 1 or len(meshes[0]['primitives']) != 1:
        raise ValueError("The transfer GLB must contain exactly one mesh primitive.")
    primitive = meshes[0]['primitives'][0]
    uv_names = {name for name in primitive['attributes'] if name.startswith('TEXCOORD_')}
    if uv_names != {'TEXCOORD_0'} or primitive.get('mode', 4) != 4:
        raise ValueError("The GLB must contain triangles and exactly one UV set (TEXCOORD_0).")
    if len(document.get('materials', [])) != 1 or primitive.get('material') != 0:
        raise ValueError("The transfer GLB must contain only its single neutral material.")
    if document.get('textures') or document.get('images') or document.get('skins'):
        raise ValueError("The transfer GLB unexpectedly contains textures, images or a skin.")


def make_checker(path, size=1024):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (size, size))
    draw = ImageDraw.Draw(image)
    palette = ((237, 72, 62), (62, 174, 238), (246, 196, 48), (112, 196, 95),
               (181, 106, 228), (240, 134, 55), (43, 191, 174), (232, 118, 173))
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 22)
    except OSError:
        font = ImageFont.load_default(size=22)
    cell = size // 8
    for row, column in itertools.product(range(8), repeat=2):
        x, y = column * cell, row * cell
        color = palette[(column + 3 * row) % len(palette)]
        draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=color, outline='black', width=3)
        draw.text((x + 10, y + 12), f'{chr(65 + column)}{8 - row}', font=font, fill='black')
        # A triangle only in the upper-left and an L only in the lower-right.
        draw.polygon(((x + 12, y + 52), (x + 12, y + 82), (x + 38, y + 52)), fill='white')
        draw.line(((x + 80, y + 85), (x + 80, y + 108), (x + 109, y + 108)), fill='black', width=5)
    draw.rectangle((3, 3, size - 4, size - 4), outline='white', width=5)
    image.save(path)


def validate_file(directory):
    """Runs in ComfyUI's Python, using the same loader call as Hy3DLoadMesh."""
    import trimesh
    path = os.path.join(directory, 'target.glb')
    _glb_contract(path)
    mesh = trimesh.load(path, force='mesh')
    if getattr(mesh.visual, 'uv', None) is None:
        raise ValueError("Trimesh did not retain the exported UV set.")
    positions, uv = np.asarray(mesh.vertices)[mesh.faces], np.asarray(mesh.visual.uv)[mesh.faces]
    with np.load(os.path.join(directory, 'source.npz'), allow_pickle=False) as source:
        result = compare_corners(source['positions'], source['uv'], positions, uv)
    np.savez(os.path.join(directory, 'loaded.npz'), positions=positions, uv=uv)
    make_checker(os.path.join(directory, 'checker.png'))
    return dict(result, trimesh_version=trimesh.__version__, uv_set='TEXCOORD_0')


def clear_preview(state):
    import bpy
    for obj in state.pop('preview_objects', []):
        try:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except ReferenceError:
            pass
    material = state.pop('preview_material', None)
    try:
        if material:
            material.use_fake_user = False
            if material.users == 0:
                bpy.data.materials.remove(material)
    except ReferenceError:
        pass
    image = state.pop('preview_image', None)
    try:
        if image and image.users == 0:
            bpy.data.images.remove(image)
    except ReferenceError:
        pass


def preview_checker(context, state):
    """Two temporary copies, preserving the original object's mesh and materials."""
    import bpy
    from . import material_utils
    assert_unchanged(context, state)
    clear_preview(state)
    directory = state['directory']
    state['preview_objects'] = []
    try:
        material = material_utils.apply_pbr_textures(
            None, os.path.join(directory, 'checker.png'),
            material_name='M_Surface_UV_Checker_' + os.path.basename(directory),
            uv_name=state['uv_name'], create_only=True)
        state['preview_material'] = material
        state['preview_image'] = next(n.image for n in material.node_tree.nodes if n.type == 'TEX_IMAGE')
        with np.load(os.path.join(directory, 'source.npz'), allow_pickle=False) as data:
            width = max(float(np.ptp(data['positions'][..., 0])), 0.1)
        for filename, label, offset in (('source.npz', 'UV Checker - SOURCE', -width * 1.2),
                                         ('loaded.npz', 'UV Checker - TRIMESH', width * 1.2)):
            with np.load(os.path.join(directory, filename), allow_pickle=False) as data:
                positions, uv = data['positions'].copy(), data['uv'].copy()
            # glTF Y-up -> Blender Z-up; no UV flip or UV re-packing.
            positions = positions[..., [0, 2, 1]]
            positions[..., 1] *= -1
            mesh = bpy.data.meshes.new(label)
            obj = bpy.data.objects.new(label, mesh)
            state['preview_objects'].append(obj)
            context.scene.collection.objects.link(obj)
            mesh.from_pydata(positions.reshape(-1, 3).tolist(), [],
                             np.arange(len(positions) * 3).reshape(-1, 3).tolist())
            layer = mesh.uv_layers.new(name=state['uv_name'])
            layer.data.foreach_set('uv', uv.reshape(-1))
            layer.active_render = True
            mesh.materials.append(material)
            obj.location.x = offset
            obj.show_name = True
        assert_unchanged(context, state)
        material_utils.set_viewport_material_shading(context)
    except Exception:
        clear_preview(state)
        raise


if __name__ == '__main__':
    import sys
    try:
        print(json.dumps(dict(ok=True, **validate_file(sys.argv[1]))))
    except Exception as exc:
        print(json.dumps(dict(ok=False, error=str(exc))))
        sys.exit(1)
