# SPDX-License-Identifier: MIT
"""
Blender import operator for 3MF files with color/paint data.

Supports Bambu Studio, OrcaSlicer, Snapmaker Orca, and compatible slicers.
"""

import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix

from .three_mf_zip import ThreeMFArchive
from .three_mf_model import parse_model_file, BuildItem, MeshObject, ObjectEntry
from .bambu_paint import decode_paint_colors, aggregate_vertex_colors, PALETTE_GENERATED


class IMPORT_OT_bambu_3mf(bpy.types.Operator, ImportHelper):
    """Import a 3MF file with multicolor paint data as vertex colors"""
    bl_idname = "import_scene.bambu_3mf"
    bl_label = "Import 3MF with Colors"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}

    # File browser filter
    filename_ext = ".3mf"
    filter_glob: StringProperty(
        default="*.3mf",
        options={'HIDDEN'},
        maxlen=255,
    )

    # Operator options
    color_attribute_name: StringProperty(
        name="Color Attribute",
        description="Name of the vertex color attribute to create",
        default="slicer_paint",
    )

    palette_source: EnumProperty(
        name="Palette Source",
        description="How to determine colors for each paint index",
        items=[
            ('AUTO', "Auto", "Try to read filament colors from slicer project metadata, fall back to generated"),
            ('GENERATED', "Generated", "Always use generated distinct colors"),
        ],
        default='AUTO',
    )

    conflict_resolution: EnumProperty(
        name="Conflict Resolution",
        description="How to resolve vertex color when adjacent faces have different paint",
        items=[
            ('MAJORITY', "Majority Vote", "Use the most common paint index among incident triangles"),
            ('LOWEST', "Lowest Index", "Use the lowest paint index among incident triangles"),
        ],
        default='MAJORITY',
    )

    import_transforms: BoolProperty(
        name="Import Build Transforms",
        description="Apply 3MF build transforms to imported objects",
        default=True,
    )

    def execute(self, context):
        return self.import_3mf(context, self.filepath)

    def import_3mf(self, context, filepath):
        try:
            archive = ThreeMFArchive(filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to open 3MF file: {e}")
            return {'CANCELLED'}

        # Collect all objects and build items from all model files
        # Key: (normalized_path, object_id) -> ObjectEntry
        all_objects: dict[tuple[str, int], ObjectEntry] = {}
        all_build_items: list[BuildItem] = []
        unit_scale = 0.001  # default millimeters

        model_files = archive.get_model_files()
        if not model_files:
            self.report({'ERROR'}, "No model files found in 3MF archive")
            return {'CANCELLED'}

        for model_path in model_files:
            try:
                xml_content = archive.read_file(model_path)
                objects, build_items, file_unit_scale = parse_model_file(
                    xml_content, model_path
                )
                # Use unit scale from first file that specifies it
                if file_unit_scale is not None:
                    unit_scale = file_unit_scale

                # Normalize the path for consistent lookup
                norm_path = self._normalize_path(model_path)

                # Merge objects (keyed by normalized path + object id)
                for obj_id, obj_entry in objects.items():
                    key = (norm_path, obj_id)
                    all_objects[key] = obj_entry

                # Adjust build item references to include source file
                for item in build_items:
                    item.source_file = norm_path
                    all_build_items.append(item)

            except Exception as e:
                self.report({'WARNING'}, f"Failed to parse {model_path}: {e}")
                continue

        if not all_objects:
            self.report({'ERROR'}, "No objects found in 3MF file")
            return {'CANCELLED'}

        # Try to get filament palette from project metadata
        palette = PALETTE_GENERATED
        if self.palette_source == 'AUTO':
            detected_palette = archive.try_get_filament_palette()
            if detected_palette:
                palette = detected_palette

        # Create Blender meshes and objects
        created_objects = []
        mesh_cache: dict[tuple, bpy.types.Mesh] = {}

        # If no build items, create objects for all mesh-containing objects
        if not all_build_items:
            for (file_path, obj_id), obj_entry in all_objects.items():
                meshes = self._resolve_meshes(
                    all_objects, file_path, obj_id, Matrix.Identity(4)
                )
                for mesh_obj, combined_transform in meshes:
                    bl_mesh = self._create_blender_mesh(
                        mesh_obj, unit_scale, palette, f"Mesh_{obj_id}"
                    )
                    bl_obj = bpy.data.objects.new(
                        mesh_obj.name or f"Object_{obj_id}", bl_mesh
                    )
                    if self.import_transforms:
                        bl_obj.matrix_world = combined_transform
                    context.collection.objects.link(bl_obj)
                    created_objects.append(bl_obj)
        else:
            # Create objects based on build items
            for item in all_build_items:
                build_transform = item.transform if item.transform else Matrix.Identity(4)
                
                # Resolve all meshes for this build item (following component refs)
                meshes = self._resolve_meshes(
                    all_objects, item.source_file, item.object_id, build_transform
                )
                
                if not meshes:
                    self.report({'WARNING'}, f"Build item references object {item.object_id} with no mesh")
                    continue

                for mesh_obj, combined_transform in meshes:
                    # Create cache key from mesh identity
                    cache_key = (id(mesh_obj),)
                    
                    # Reuse mesh if already created
                    if cache_key in mesh_cache:
                        bl_mesh = mesh_cache[cache_key]
                    else:
                        bl_mesh = self._create_blender_mesh(
                            mesh_obj, unit_scale, palette,
                            mesh_obj.name or f"Mesh_{item.object_id}"
                        )
                        mesh_cache[cache_key] = bl_mesh

                    bl_obj = bpy.data.objects.new(
                        mesh_obj.name or f"Object_{item.object_id}", bl_mesh
                    )

                    if self.import_transforms:
                        # Apply unit scale to translation part of transform
                        scaled_transform = combined_transform.copy()
                        scaled_transform[0][3] *= unit_scale
                        scaled_transform[1][3] *= unit_scale
                        scaled_transform[2][3] *= unit_scale
                        bl_obj.matrix_world = scaled_transform

                    context.collection.objects.link(bl_obj)
                    created_objects.append(bl_obj)

        # Select imported objects
        bpy.ops.object.select_all(action='DESELECT')
        for obj in created_objects:
            obj.select_set(True)
        if created_objects:
            context.view_layer.objects.active = created_objects[0]

        self.report({'INFO'}, f"Imported {len(created_objects)} object(s) from 3MF")
        return {'FINISHED'}

    def _normalize_path(self, path: str) -> str:
        """Normalize a file path for consistent lookup."""
        # Remove leading slashes and normalize separators
        path = path.replace('\\', '/').lstrip('/')
        return path.lower()

    def _resolve_meshes(
        self,
        all_objects: dict[tuple[str, int], ObjectEntry],
        source_file: str,
        object_id: int,
        parent_transform: Matrix,
        depth: int = 0
    ) -> list[tuple[MeshObject, Matrix]]:
        """
        Resolve an object reference to actual mesh(es), following component refs.
        
        Returns list of (MeshObject, combined_transform) tuples.
        """
        if depth > 10:  # Prevent infinite loops
            return []

        # Find the object
        key = (source_file, object_id)
        obj_entry = all_objects.get(key)
        
        if obj_entry is None:
            # Try to find by object_id alone (for simple files)
            for (fp, oid), entry in all_objects.items():
                if oid == object_id:
                    obj_entry = entry
                    break
        
        if obj_entry is None:
            return []

        results: list[tuple[MeshObject, Matrix]] = []

        # If this object has a direct mesh, include it
        if obj_entry.mesh is not None:
            results.append((obj_entry.mesh, parent_transform))

        # If this object has components, resolve them recursively
        for comp in obj_entry.components:
            # Determine the file path for the component
            if comp.path:
                # Component references external file
                comp_file = self._normalize_path(comp.path)
            else:
                # Component is in same file
                comp_file = source_file

            # Combine transforms
            if comp.transform:
                combined = parent_transform @ comp.transform
            else:
                combined = parent_transform

            # Recursively resolve
            sub_meshes = self._resolve_meshes(
                all_objects, comp_file, comp.object_id, combined, depth + 1
            )
            results.extend(sub_meshes)

        return results

    def _create_blender_mesh(
        self,
        mesh_obj: MeshObject,
        unit_scale: float,
        palette: list[tuple[float, float, float, float]],
        name: str
    ) -> bpy.types.Mesh:
        """Create a Blender mesh from parsed 3MF mesh object."""
        # Scale vertices
        scaled_verts = [
            (v[0] * unit_scale, v[1] * unit_scale, v[2] * unit_scale)
            for v in mesh_obj.vertices
        ]

        # Create mesh
        bl_mesh = bpy.data.meshes.new(name)
        bl_mesh.from_pydata(scaled_verts, [], mesh_obj.triangles)
        bl_mesh.update()

        # Add vertex colors if we have paint data
        if mesh_obj.triangle_paint:
            # Decode paint codes to palette indices
            paint_indices = decode_paint_colors(mesh_obj.triangle_paint)

            # Aggregate to per-vertex colors
            use_majority = (self.conflict_resolution == 'MAJORITY')
            vertex_colors = aggregate_vertex_colors(
                len(mesh_obj.vertices),
                mesh_obj.triangles,
                paint_indices,
                palette,
                use_majority=use_majority
            )

            # Create color attribute (POINT domain = per-vertex)
            color_attr = bl_mesh.color_attributes.new(
                name=self.color_attribute_name,
                type='BYTE_COLOR',
                domain='POINT'
            )

            # Fill color data
            for i, color in enumerate(vertex_colors):
                color_attr.data[i].color = color

        return bl_mesh

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "color_attribute_name")
        layout.prop(self, "palette_source")
        layout.prop(self, "conflict_resolution")
        layout.prop(self, "import_transforms")
