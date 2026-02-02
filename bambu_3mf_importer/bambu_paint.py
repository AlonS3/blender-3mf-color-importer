# SPDX-License-Identifier: MIT
"""
Slicer paint_color decoding and vertex color aggregation.

Supports the paint_color encoding used by Bambu Studio, OrcaSlicer,
Snapmaker Orca, and compatible slicers.
"""

from collections import Counter
import colorsys


# Known Bambu Studio paint_color codes mapped to palette/extruder indices
# Based on actual Bambu Studio encoding (numbers read right-to-left in hex):
# - 0 = none/base (extruder 1, index 0)
# - 4 = extruder 1 (index 0)
# - 8 = extruder 2 (index 1)
# - 0C = extruder 3 (index 2)
# - 1C = extruder 4 (index 3)
# - 2C = extruder 5 (index 4)
# - etc.
#
# Short codes (for whole-triangle coloring):
BAMBU_PAINT_CODE_MAP = {
    '0': 0,    # Base/none - extruder 1
    '4': 0,    # Extruder 1
    '8': 1,    # Extruder 2
    '0C': 2,   # Extruder 3
    'C0': 2,   # Extruder 3 (alternate reading)
    '1C': 3,   # Extruder 4
    'C1': 3,   # Extruder 4 (alternate reading)
    '2C': 4,   # Extruder 5
    'C2': 4,   # Extruder 5 (alternate reading)
    '3C': 5,   # Extruder 6
    'C3': 5,   # Extruder 6 (alternate reading)
    '4C': 6,   # Extruder 7
    'C4': 6,   # Extruder 7 (alternate reading)
    '5C': 7,   # Extruder 8
    'C5': 7,   # Extruder 8 (alternate reading)
    '6C': 8,   # Extruder 9
    'C6': 8,   # Extruder 9 (alternate reading)
    '7C': 9,   # Extruder 10
    'C7': 9,   # Extruder 10 (alternate reading)
}

# For long paint strings (sub-triangle painting), we need to parse pairs
# The encoding uses nibble pairs where:
# - '0' nibble = base/extruder 1
# - '4' nibble = extruder 1 (same as base in this context)
# - '8' nibble = extruder 2
# - 'C' followed by digit = extruder 3+ (C0=ext3, C1=ext4, etc.)
# - digit followed by 'C' = same (0C=ext3, 1C=ext4, etc.)


def generate_distinct_colors(count: int) -> list[tuple[float, float, float, float]]:
    """
    Generate a list of visually distinct colors using HSV color space.
    
    Uses golden ratio to distribute hues evenly.
    """
    colors = []
    golden_ratio_conjugate = 0.618033988749895
    hue = 0.0
    
    for i in range(count):
        # Vary saturation and value slightly for more distinction
        saturation = 0.7 + (i % 3) * 0.1
        value = 0.9 - (i % 2) * 0.15
        
        r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
        colors.append((r, g, b, 1.0))
        
        hue = (hue + golden_ratio_conjugate) % 1.0
    
    return colors


# Default generated palette with 16 distinct colors
PALETTE_GENERATED = generate_distinct_colors(16)


def decode_paint_code(paint_code: str | None) -> int:
    """
    Decode a Bambu paint_color string to a palette index.
    
    Handles both simple codes (like "8") and complex sub-triangle
    encoded strings (like "0008003880003880833888000300803808833888088383303").
    
    For complex strings, parses nibble pairs and returns the dominant color.
    
    Returns:
        Integer palette index (0-based, corresponding to extruder index)
    """
    if paint_code is None or paint_code == '':
        return 0  # Base color / extruder 1
    
    code = paint_code.strip().upper()
    
    # Try known short codes first
    if code in BAMBU_PAINT_CODE_MAP:
        return BAMBU_PAINT_CODE_MAP[code]
    
    # For very short codes (1-2 chars), try the mapping
    if len(code) <= 2:
        for key, value in BAMBU_PAINT_CODE_MAP.items():
            if key == code:
                return value
        # Unknown short code - default to base
        return 0
    
    # Long string: sub-triangle encoding
    # Parse the string to extract color indices
    # The encoding uses nibbles where:
    # - '0' = base/extruder 1 (index 0)
    # - '3' appears in combinations
    # - '8' = extruder 2 (index 1)  
    # - 'C' with digit = extruder 3+ (0C/C0=ext3, 1C/C1=ext4, etc.)
    
    color_counts: Counter[int] = Counter()
    i = 0
    
    while i < len(code):
        char = code[i]
        
        # Check for two-character patterns with 'C'
        if i + 1 < len(code):
            pair = code[i:i+2]
            # Check both orderings: XC and CX
            if pair in BAMBU_PAINT_CODE_MAP:
                color_counts[BAMBU_PAINT_CODE_MAP[pair]] += 1
                i += 2
                continue
            # Try reversed pair
            reversed_pair = pair[1] + pair[0]
            if reversed_pair in BAMBU_PAINT_CODE_MAP:
                color_counts[BAMBU_PAINT_CODE_MAP[reversed_pair]] += 1
                i += 2
                continue
        
        # Single character interpretation
        if char == '0':
            color_counts[0] += 1  # Base/extruder 1
        elif char == '4':
            color_counts[0] += 1  # Extruder 1
        elif char == '8':
            color_counts[1] += 1  # Extruder 2
        elif char == '3':
            # '3' often appears in combinations, treat as noise or base
            color_counts[0] += 1
        elif char == 'C':
            # Standalone C - might be part of a pair we missed
            # Check if next char is a digit for CX pattern
            if i + 1 < len(code) and code[i+1].isdigit():
                digit = int(code[i+1])
                color_counts[2 + digit] += 1  # C0=ext3, C1=ext4, etc.
                i += 2
                continue
            # Or previous char might form XC
            # Just skip standalone C
            pass
        
        i += 1
    
    if not color_counts:
        return 0  # No recognizable colors
    
    # Find the most common non-zero color (prefer painted over base)
    non_zero_counts = {k: v for k, v in color_counts.items() if k != 0}
    
    if non_zero_counts:
        # Return most frequent non-zero color
        return max(non_zero_counts.keys(), key=lambda k: non_zero_counts[k])
    else:
        # Only base color found
        return 0


def decode_paint_colors(triangle_paint: list[str | None]) -> list[int]:
    """
    Decode a list of triangle paint_color values to palette indices.
    
    Args:
        triangle_paint: List of paint_color attribute values, one per triangle
        
    Returns:
        List of palette indices (0-based integers)
    """
    return [decode_paint_code(code) for code in triangle_paint]


def aggregate_vertex_colors(
    vertex_count: int,
    triangles: list[tuple[int, int, int]],
    paint_indices: list[int],
    palette: list[tuple[float, float, float, float]],
    use_majority: bool = True
) -> list[tuple[float, float, float, float]]:
    """
    Aggregate per-triangle paint to per-vertex colors.
    
    Since triangles share vertices but each triangle has its own paint color,
    we need a strategy to assign a single color to each vertex.
    
    Args:
        vertex_count: Number of vertices in the mesh
        triangles: List of (v1, v2, v3) vertex index tuples
        paint_indices: List of palette indices, one per triangle
        palette: List of RGBA color tuples
        use_majority: If True, use majority vote; if False, use lowest index
        
    Returns:
        List of RGBA color tuples, one per vertex
    """
    # Build per-vertex list of incident triangle paint indices
    vertex_paint_indices: list[list[int]] = [[] for _ in range(vertex_count)]
    
    for tri_idx, (v1, v2, v3) in enumerate(triangles):
        paint_idx = paint_indices[tri_idx]
        vertex_paint_indices[v1].append(paint_idx)
        vertex_paint_indices[v2].append(paint_idx)
        vertex_paint_indices[v3].append(paint_idx)
    
    # Resolve each vertex's color
    vertex_colors: list[tuple[float, float, float, float]] = []
    default_color = palette[0] if palette else (1.0, 1.0, 1.0, 1.0)
    
    for vert_idx, incident_paints in enumerate(vertex_paint_indices):
        if not incident_paints:
            # Isolated vertex (shouldn't happen in valid mesh)
            vertex_colors.append(default_color)
            continue
        
        if use_majority:
            # Majority vote with lowest-index tie-breaker
            counter = Counter(incident_paints)
            max_count = max(counter.values())
            # Among tied counts, pick lowest paint index
            candidates = [idx for idx, cnt in counter.items() if cnt == max_count]
            chosen_idx = min(candidates)
        else:
            # Simple: lowest paint index wins
            chosen_idx = min(incident_paints)
        
        # Map to palette color (with bounds check)
        if 0 <= chosen_idx < len(palette):
            vertex_colors.append(palette[chosen_idx])
        else:
            # Wrap around if palette is smaller than index
            vertex_colors.append(palette[chosen_idx % len(palette)])
    
    return vertex_colors
