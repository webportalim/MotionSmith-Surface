"""Apply an UltraTex bake and its UV layout to the original Blender mesh."""

import os
import bpy
import mathutils


def apply_baked_uvs(context, obj, glb_path):
    """Transfer baked UV coordinates from imported GLB to target Blender mesh using KDTree spatial matching."""
    selected = list(context.selected_objects)
    active = context.view_layer.objects.active
    original = {kind: set(getattr(bpy.data, kind)) for kind in
                ("objects", "meshes", "materials", "images", "collections")}
    try:
        bpy.ops.import_scene.gltf(filepath=glb_path, import_pack_images=False,
                                  import_scene_as_collection=False)
        sources = [o for o in bpy.data.objects if o not in original["objects"] and o.type == "MESH"]
        if not sources:
            raise ValueError("The bake has no mesh/UV data in the GLB.")
        source = sources[0]
        s_mesh = source.data
        s_uv = s_mesh.uv_layers.active
        if s_uv is None:
            raise ValueError("The baked mesh has no UV map.")

        s_world = source.matrix_world
        t_world = obj.matrix_world

        s_mesh.calc_loop_triangles()
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        t_mesh = obj.data
        t_mesh.calc_loop_triangles()

        # Spatial index (KDTree) on source triangle centers for sub-micron matching
        s_tris = s_mesh.loop_triangles
        s_tri_count = len(s_tris)
        kd_centers = mathutils.kdtree.KDTree(s_tri_count)
        for i, tri in enumerate(s_tris):
            pts = [s_world @ s_mesh.vertices[s_mesh.loops[l_idx].vertex_index].co for l_idx in tri.loops]
            center = (pts[0] + pts[1] + pts[2]) / 3.0
            kd_centers.insert(center, i)
        kd_centers.balance()

        # Fallback spatial index on source loops
        kd_loops = mathutils.kdtree.KDTree(len(s_mesh.loops))
        for l_idx, loop in enumerate(s_mesh.loops):
            pt = s_world @ s_mesh.vertices[loop.vertex_index].co
            kd_loops.insert(pt, l_idx)
        kd_loops.balance()

        uv = t_mesh.uv_layers.get("UltraTexUV") or t_mesh.uv_layers.new(name="UltraTexUV")
        assigned_loops = set()

        # Primary pass: Match loop triangles by center and transfer corner UVs
        for t_tri in t_mesh.loop_triangles:
            t_pts = [t_world @ t_mesh.vertices[t_mesh.loops[l_idx].vertex_index].co for l_idx in t_tri.loops]
            t_center = (t_pts[0] + t_pts[1] + t_pts[2]) / 3.0
            _, s_idx, dist = kd_centers.find(t_center)
            if dist < 0.05:
                s_tri = s_tris[s_idx]
                s_corners = [(s_world @ s_mesh.vertices[s_mesh.loops[sl_idx].vertex_index].co,
                              s_uv.data[sl_idx].uv) for sl_idx in s_tri.loops]
                for l_idx, t_pt in zip(t_tri.loops, t_pts):
                    best_uv = min(s_corners, key=lambda c: (c[0] - t_pt).length_squared)[1]
                    uv.data[l_idx].uv = best_uv
                    assigned_loops.add(l_idx)

        # Secondary pass: Fallback for any unassigned loops
        if len(assigned_loops) < len(t_mesh.loops):
            for l_idx, loop in enumerate(t_mesh.loops):
                if l_idx not in assigned_loops:
                    t_pt = t_world @ t_mesh.vertices[loop.vertex_index].co
                    _, s_l_idx, _ = kd_loops.find(t_pt)
                    uv.data[l_idx].uv = s_uv.data[s_l_idx].uv
                    assigned_loops.add(l_idx)

        t_mesh.uv_layers.active = uv
        uv.active_render = True
        t_mesh.update()
        return uv.name
    finally:
        for item in set(bpy.data.objects) - original["objects"]:
            bpy.data.objects.remove(item, do_unlink=True)
        for kind in ("meshes", "materials", "images", "collections"):
            data = getattr(bpy.data, kind)
            for item in set(data) - original[kind]:
                if item.users == 0:
                    data.remove(item)
        for item in context.selected_objects:
            item.select_set(False)
        for item in selected:
            if item.name in context.view_layer.objects:
                item.select_set(True)
        context.view_layer.objects.active = active


def apply_pbr_textures(obj, albedo_path, orm_path=None, material_name="M_UltraTex_Surface", uv_name=None,
                       roughness_path=None, metallic_path=None, normal_path=None, slot_policy="ALL_SLOTS",
                       height_path=None, create_only=False):
    if not create_only and (obj is None or obj.type != "MESH"):
        raise ValueError("Select a mesh to receive the bake.")
    if not albedo_path or not os.path.isfile(albedo_path):
        raise FileNotFoundError(f"Albedo not found: {albedo_path}")
    if orm_path and not os.path.isfile(orm_path):
        raise FileNotFoundError(f"ORM not found: {orm_path}")
    if normal_path and not os.path.isfile(normal_path):
        normal_path = None
    albedo = bpy.data.images.load(albedo_path, check_existing=True)
    albedo.reload()
    albedo.colorspace_settings.name = "sRGB"
    albedo.pack()
    orm = None
    if orm_path:
        orm = bpy.data.images.load(orm_path, check_existing=True)
        orm.reload()
        orm.colorspace_settings.name = "Non-Color"
        orm.pack()
    mat = bpy.data.materials.get(material_name) or bpy.data.materials.new(material_name)
    if mat.users > 1:
        mat = mat.copy()
    mat.use_nodes = True
    map_label = "Chord" if material_name.startswith("M_Chord_") else "UltraTex"
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (650, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (350, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = uv_name or (obj.data.uv_layers.active.name if obj and obj.data.uv_layers.active else "")
    uv.location = (-700, 200)
    coordinates = uv.outputs["UV"]
    if map_label == "Chord":
        uv.location = (-1000, 200)
        mapping = nodes.new("ShaderNodeMapping")
        mapping.label = "PBR Mapping"
        mapping.vector_type = 'POINT'
        mapping.location = (-750, 200)
        links.new(coordinates, mapping.inputs["Vector"])
        coordinates = mapping.outputs["Vector"]
    tex = nodes.new("ShaderNodeTexImage")
    tex.image, tex.label, tex.location = albedo, f"{map_label} Albedo", (-400, 200)
    links.new(coordinates, tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if orm:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image, tex.label, tex.location = orm, "UltraTex ORM (AO/R/M)", (-400, -150)
        links.new(coordinates, tex.inputs["Vector"])
        separate = nodes.new("ShaderNodeSeparateColor")
        separate.location = (-100, -150)
        links.new(tex.outputs["Color"], separate.inputs["Color"])
        links.new(separate.outputs["Green"], bsdf.inputs["Roughness"])
        links.new(separate.outputs["Blue"], bsdf.inputs["Metallic"])
    for path, socket in ((roughness_path, "Roughness"), (metallic_path, "Metallic")):
        if not path:
            continue
        image = bpy.data.images.load(path, check_existing=True)
        image.reload()
        image.colorspace_settings.name = "Non-Color"
        image.pack()
        tex = nodes.new("ShaderNodeTexImage")
        tex.image, tex.label = image, map_label + " " + socket
        tex.location = (-400, -450 if socket == "Roughness" else -750)
        links.new(coordinates, tex.inputs["Vector"])
        links.new(tex.outputs["Color"], bsdf.inputs[socket])
    if normal_path:
        norm_img = bpy.data.images.load(normal_path, check_existing=True)
        norm_img.reload()
        norm_img.colorspace_settings.name = "Non-Color"
        norm_img.pack()
        tex_norm = nodes.new("ShaderNodeTexImage")
        tex_norm.image, tex_norm.label = norm_img, map_label + " Normal"
        tex_norm.location = (-400, -950)
        norm_node = nodes.new("ShaderNodeNormalMap")
        norm_node.space = 'TANGENT'
        norm_node.uv_map = uv_name or (obj.data.uv_layers.active.name if obj and obj.data.uv_layers.active else '')
        norm_node.location = (-100, -950)
        links.new(coordinates, tex_norm.inputs["Vector"])
        links.new(tex_norm.outputs["Color"], norm_node.inputs["Color"])
        links.new(norm_node.outputs["Normal"], bsdf.inputs["Normal"])
    if height_path:
        height = bpy.data.images.load(height_path, check_existing=True)
        height.reload()
        height.colorspace_settings.name = "Non-Color"
        height.pack()
        tex_height = nodes.new("ShaderNodeTexImage")
        tex_height.image, tex_height.label = height, "Height"
        tex_height.location = (-400, -1250)
        links.new(coordinates, tex_height.inputs["Vector"])
    if create_only:
        mat.use_fake_user = True
        return mat
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    if slot_policy == "ACTIVE_SLOT" and obj.material_slots:
        active_idx = max(0, min(obj.active_material_index, len(obj.material_slots) - 1))
        obj.material_slots[active_idx].material = mat
        if active_idx < len(obj.data.materials):
            obj.data.materials[active_idx] = mat
    elif slot_policy == "NEW_SLOT":
        obj.data.materials.append(mat)
        new_idx = len(obj.material_slots) - 1
        obj.active_material_index = new_idx
        selected_polys = [p for p in obj.data.polygons if p.select]
        target_polys = selected_polys if selected_polys else obj.data.polygons
        for polygon in target_polys:
            polygon.material_index = new_idx
    else:  # ALL_SLOTS (default)
        if not obj.material_slots:
            obj.data.materials.append(mat)
        else:
            for slot in obj.material_slots:
                slot.material = mat
            for i in range(len(obj.data.materials)):
                obj.data.materials[i] = mat
        for polygon in obj.data.polygons:
            polygon.material_index = 0
        obj.active_material_index = 0
    obj.data.update()
    return mat


def set_viewport_material_shading(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.shading.type = "MATERIAL"
                area.tag_redraw()
