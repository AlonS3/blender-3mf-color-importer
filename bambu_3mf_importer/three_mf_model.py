# SPDX-License-Identifier: MIT
"""
3MF model XML parsing - extract mesh geometry, build items, and transforms.

Supports Bambu Studio, OrcaSlicer, Snapmaker Orca, and compatible slicers.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from mathutils import Matrix
import re


@dataclass
class MeshObject:
    """Represents a 3MF mesh object with actual geometry."""
    id: int
    name: str | None
    vertices: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]
    triangle_paint: list[str | None]  # Per-triangle paint_color attribute values


@dataclass
class ComponentRef:
    """Represents a reference to another object (possibly in another file)."""
    path: str | None  # p:path attribute - file path (None if same file)
    object_id: int    # objectid in the referenced file
    transform: 'Matrix | None'  # Local transform for this component


@dataclass
class ObjectEntry:
    """Represents any 3MF object - either a mesh or a component container."""
    id: int
    name: str | None
    mesh: MeshObject | None  # Actual mesh data (if this object has geometry)
    components: list[ComponentRef]  # Component references (if this is a container)


@dataclass
class BuildItem:
    """Represents a 3MF build item (instance of an object with transform)."""
    object_id: int
    transform: Matrix | None
    source_file: str | None = None


# 3MF namespace URIs (we match by local name to be namespace-agnostic)
NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def local_name(tag: str) -> str:
    """Extract local name from a potentially namespaced tag."""
    if tag.startswith('{'):
        return tag.split('}', 1)[1]
    return tag


def find_elements_by_local_name(parent: ET.Element, local: str) -> list[ET.Element]:
    """Find all child elements matching a local name (ignoring namespace)."""
    results = []
    for child in parent:
        if local_name(child.tag) == local:
            results.append(child)
    return results


def find_element_by_local_name(parent: ET.Element, local: str) -> ET.Element | None:
    """Find first child element matching a local name (ignoring namespace)."""
    for child in parent:
        if local_name(child.tag) == local:
            return child
    return None


def get_attr(elem: ET.Element, attr_name: str, default: str | None = None) -> str | None:
    """
    Get attribute value, trying both with and without namespace prefix.
    Also handles Bambu's custom attributes like 'paint_color'.
    """
    # Try direct attribute name
    if attr_name in elem.attrib:
        return elem.attrib[attr_name]
    
    # Try with common namespace prefixes stripped
    for key, value in elem.attrib.items():
        # Handle namespaced attributes like {ns}attr
        if key.endswith('}' + attr_name):
            return value
        # Handle prefixed attributes like p:attr
        if ':' in key and key.split(':', 1)[1] == attr_name:
            return value
    
    return default


def parse_transform(transform_str: str) -> Matrix | None:
    """
    Parse a 3MF transform string into a Blender Matrix.
    
    3MF uses a 3x4 affine matrix stored as 12 space-separated floats:
    m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32
    
    This represents the matrix:
    | m00 m01 m02 0 |
    | m10 m11 m12 0 |
    | m20 m21 m22 0 |
    | m30 m31 m32 1 |
    """
    if not transform_str:
        return None
    
    try:
        values = [float(v) for v in transform_str.strip().split()]
        if len(values) != 12:
            return None
        
        # 3MF matrix layout to Blender 4x4 matrix
        # 3MF: row-major m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32
        m = values
        matrix = Matrix((
            (m[0], m[3], m[6], m[9]),
            (m[1], m[4], m[7], m[10]),
            (m[2], m[5], m[8], m[11]),
            (0.0,  0.0,  0.0,  1.0)
        ))
        return matrix
    except (ValueError, IndexError):
        return None


def parse_unit_scale(unit_str: str | None) -> float | None:
    """
    Convert 3MF unit string to scale factor (to convert to meters).
    
    3MF supports: micron, millimeter, centimeter, inch, foot, meter
    Default is millimeter if not specified.
    """
    if not unit_str:
        return None  # Let caller use default
    
    unit_lower = unit_str.lower()
    scales = {
        'micron': 0.000001,
        'millimeter': 0.001,
        'centimeter': 0.01,
        'inch': 0.0254,
        'foot': 0.3048,
        'meter': 1.0,
    }
    return scales.get(unit_lower)


def parse_model_file(
    xml_content: bytes,
    source_path: str
) -> tuple[dict[int, ObjectEntry], list[BuildItem], float | None]:
    """
    Parse a 3MF .model XML file.
    
    Returns:
        - Dictionary of object_id -> ObjectEntry (may contain mesh or component refs)
        - List of BuildItems
        - Unit scale factor (or None if not specified)
    """
    root = ET.fromstring(xml_content)
    
    # Get unit scale from model element
    unit_str = get_attr(root, 'unit')
    unit_scale = parse_unit_scale(unit_str)
    
    objects: dict[int, ObjectEntry] = {}
    build_items: list[BuildItem] = []
    
    # Find resources element
    resources_elem = find_element_by_local_name(root, 'resources')
    if resources_elem is not None:
        # Parse all object elements
        for obj_elem in find_elements_by_local_name(resources_elem, 'object'):
            obj_entry = _parse_object(obj_elem)
            if obj_entry is not None:
                objects[obj_entry.id] = obj_entry
    
    # Find build element
    build_elem = find_element_by_local_name(root, 'build')
    if build_elem is not None:
        for item_elem in find_elements_by_local_name(build_elem, 'item'):
            build_item = _parse_build_item(item_elem)
            if build_item is not None:
                build_items.append(build_item)
    
    return objects, build_items, unit_scale


def _parse_object(obj_elem: ET.Element) -> ObjectEntry | None:
    """Parse an object element - may contain a mesh or component references."""
    obj_id_str = get_attr(obj_elem, 'id')
    if obj_id_str is None:
        return None
    
    try:
        obj_id = int(obj_id_str)
    except ValueError:
        return None
    
    obj_name = get_attr(obj_elem, 'name')
    
    mesh_obj: MeshObject | None = None
    components: list[ComponentRef] = []
    
    # Try to parse mesh element
    mesh_elem = find_element_by_local_name(obj_elem, 'mesh')
    if mesh_elem is not None:
        mesh_obj = _parse_mesh(obj_id, obj_name, mesh_elem)
    
    # Try to parse components element (3MF Production Extension)
    components_elem = find_element_by_local_name(obj_elem, 'components')
    if components_elem is not None:
        for comp_elem in find_elements_by_local_name(components_elem, 'component'):
            comp_ref = _parse_component(comp_elem)
            if comp_ref is not None:
                components.append(comp_ref)
    
    # Return None only if there's neither mesh nor components
    if mesh_obj is None and not components:
        return None
    
    return ObjectEntry(
        id=obj_id,
        name=obj_name,
        mesh=mesh_obj,
        components=components
    )


def _parse_mesh(obj_id: int, obj_name: str | None, mesh_elem: ET.Element) -> MeshObject | None:
    """Parse a mesh element containing vertices and triangles."""
    # Parse vertices
    vertices_elem = find_element_by_local_name(mesh_elem, 'vertices')
    if vertices_elem is None:
        return None
    
    vertices: list[tuple[float, float, float]] = []
    for vertex_elem in find_elements_by_local_name(vertices_elem, 'vertex'):
        x = float(get_attr(vertex_elem, 'x', '0'))
        y = float(get_attr(vertex_elem, 'y', '0'))
        z = float(get_attr(vertex_elem, 'z', '0'))
        vertices.append((x, y, z))
    
    if not vertices:
        return None
    
    # Parse triangles
    triangles_elem = find_element_by_local_name(mesh_elem, 'triangles')
    if triangles_elem is None:
        return None
    
    triangles: list[tuple[int, int, int]] = []
    triangle_paint: list[str | None] = []
    
    for tri_elem in find_elements_by_local_name(triangles_elem, 'triangle'):
        v1 = int(get_attr(tri_elem, 'v1', '0'))
        v2 = int(get_attr(tri_elem, 'v2', '0'))
        v3 = int(get_attr(tri_elem, 'v3', '0'))
        triangles.append((v1, v2, v3))
        
        # Get Bambu paint_color attribute (may not exist)
        paint_color = get_attr(tri_elem, 'paint_color')
        triangle_paint.append(paint_color)
    
    if not triangles:
        return None
    
    return MeshObject(
        id=obj_id,
        name=obj_name,
        vertices=vertices,
        triangles=triangles,
        triangle_paint=triangle_paint
    )


def _parse_component(comp_elem: ET.Element) -> ComponentRef | None:
    """Parse a component reference element."""
    # objectid is required
    obj_id_str = get_attr(comp_elem, 'objectid')
    if obj_id_str is None:
        return None
    
    try:
        obj_id = int(obj_id_str)
    except ValueError:
        return None
    
    # p:path is optional - if present, references an external file
    # Try various attribute names for path (namespaced)
    path = get_attr(comp_elem, 'path')
    
    # Parse transform if present
    transform_str = get_attr(comp_elem, 'transform')
    transform = parse_transform(transform_str)
    
    return ComponentRef(
        path=path,
        object_id=obj_id,
        transform=transform
    )


def _parse_build_item(item_elem: ET.Element) -> BuildItem | None:
    """Parse a build item element."""
    obj_id_str = get_attr(item_elem, 'objectid')
    if obj_id_str is None:
        return None
    
    try:
        obj_id = int(obj_id_str)
    except ValueError:
        return None
    
    transform_str = get_attr(item_elem, 'transform')
    transform = parse_transform(transform_str)
    
    return BuildItem(object_id=obj_id, transform=transform)
