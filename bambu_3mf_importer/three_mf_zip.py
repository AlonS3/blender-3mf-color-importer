# SPDX-License-Identifier: MIT
"""
3MF archive handling - ZIP operations and model file discovery.

Supports Bambu Studio, OrcaSlicer, Snapmaker Orca, and compatible slicers.
"""

import zipfile
import json
import re
from pathlib import PurePosixPath


class ThreeMFArchive:
    """
    Wrapper around a 3MF file (which is a ZIP archive).
    
    Handles discovery of model files following both:
    - 3MF Core Specification (single 3D/3dmodel.model)
    - 3MF Production Extension (multiple object_*.model files in 3D/Objects/)
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.zipfile = zipfile.ZipFile(filepath, 'r')
        self._model_files: list[str] | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if self.zipfile:
            self.zipfile.close()
            self.zipfile = None

    def namelist(self) -> list[str]:
        """Return list of all files in the archive."""
        return self.zipfile.namelist()

    def read_file(self, path: str) -> bytes:
        """Read a file from the archive."""
        return self.zipfile.read(path)

    def get_model_files(self) -> list[str]:
        """
        Discover all .model files in the archive.
        
        Returns paths in order of priority:
        1. Root model file (3D/3dmodel.model)
        2. Object model files (3D/Objects/*.model)
        3. Any other .model files
        """
        if self._model_files is not None:
            return self._model_files

        all_files = self.namelist()
        model_files = []
        root_model = None
        object_models = []
        other_models = []

        for path in all_files:
            if not path.lower().endswith('.model'):
                continue

            # Normalize path for comparison
            norm_path = path.replace('\\', '/')
            
            # Check if this is the root model
            if norm_path.lower() == '3d/3dmodel.model':
                root_model = path
            elif '/3d/objects/' in norm_path.lower() or norm_path.lower().startswith('3d/objects/'):
                object_models.append(path)
            else:
                other_models.append(path)

        # Build ordered list
        if root_model:
            model_files.append(root_model)
        model_files.extend(sorted(object_models))
        model_files.extend(sorted(other_models))

        self._model_files = model_files
        return model_files

    def try_get_filament_palette(self) -> list[tuple[float, float, float, float]] | None:
        """
        Attempt to extract filament colors from Bambu Studio project metadata.
        
        Bambu Studio stores project settings in various JSON/config files within
        the 3MF archive. This method tries to find filament color definitions.
        
        Returns a list of RGBA tuples (0-1 range) if found, None otherwise.
        """
        # Common locations for Bambu Studio metadata
        # project_settings.config contains filament_colour array - check it first
        metadata_paths = [
            'Metadata/project_settings.config',
            'Metadata/model_settings.config', 
            'Metadata/slice_info.config',
            '.config/filament_settings.config',
        ]

        # Also check for any JSON-like files in Metadata/
        all_files = self.namelist()
        for path in all_files:
            if 'metadata' in path.lower() and (
                path.endswith('.config') or 
                path.endswith('.json') or
                path.endswith('.xml')
            ):
                if path not in metadata_paths:
                    metadata_paths.append(path)

        for path in metadata_paths:
            try:
                content = self.read_file(path)
                palette = self._parse_filament_colors(content)
                if palette:
                    return palette
            except (KeyError, zipfile.BadZipFile):
                continue

        return None

    def _parse_filament_colors(self, content: bytes) -> list[tuple[float, float, float, float]] | None:
        """
        Parse filament colors from config/JSON content.
        
        Looks for patterns like:
        - "filament_colour" : ["#RRGGBB", ...]
        - filament_colour = #RRGGBB
        - color="#RRGGBB"
        """
        try:
            text = content.decode('utf-8', errors='ignore')
        except:
            return None

        colors = []

        # Try JSON parsing first
        try:
            data = json.loads(text)
            colors = self._extract_colors_from_dict(data)
            if colors:
                return colors
        except json.JSONDecodeError:
            pass

        # Try regex patterns for hex colors associated with filament
        # Pattern: filament_colour = #RRGGBB or "filament_colour": "#RRGGBB"
        hex_pattern = re.compile(r'filament[_\s]*colou?r["\s:=]+["\']?(#[0-9A-Fa-f]{6})["\']?', re.IGNORECASE)
        matches = hex_pattern.findall(text)
        if matches:
            for hex_color in matches:
                rgba = self._hex_to_rgba(hex_color)
                if rgba:
                    colors.append(rgba)
            if colors:
                return colors

        # Try to find any array of hex colors
        array_pattern = re.compile(r'\[((?:\s*"#[0-9A-Fa-f]{6}"\s*,?\s*)+)\]')
        array_match = array_pattern.search(text)
        if array_match:
            hex_in_array = re.findall(r'#[0-9A-Fa-f]{6}', array_match.group(1))
            for hex_color in hex_in_array:
                rgba = self._hex_to_rgba(hex_color)
                if rgba:
                    colors.append(rgba)
            if colors:
                return colors

        return None

    def _extract_colors_from_dict(self, data: dict | list, depth: int = 0) -> list[tuple[float, float, float, float]]:
        """Recursively search dict/list for filament color arrays."""
        if depth > 10:
            return []

        colors = []

        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                # Match keys like "filament_colour", "filament_color", "filamentcolour", etc.
                is_filament_color = (
                    key_lower == 'filament_colour' or
                    key_lower == 'filament_color' or
                    ('filament' in key_lower and ('color' in key_lower or 'colour' in key_lower))
                )
                if is_filament_color:
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, str) and item.startswith('#'):
                                rgba = self._hex_to_rgba(item)
                                if rgba:
                                    colors.append(rgba)
                        # If we found colors in filament_colour, return immediately
                        # (don't continue searching, this is the authoritative source)
                        if colors:
                            return colors
                    elif isinstance(value, str) and value.startswith('#'):
                        rgba = self._hex_to_rgba(value)
                        if rgba:
                            colors.append(rgba)
                elif isinstance(value, (dict, list)):
                    found = self._extract_colors_from_dict(value, depth + 1)
                    if found:
                        return found  # Return first found palette
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    found = self._extract_colors_from_dict(item, depth + 1)
                    if found:
                        return found

        return colors

    def _hex_to_rgba(self, hex_color: str) -> tuple[float, float, float, float] | None:
        """Convert #RRGGBB to (r, g, b, a) tuple with values 0-1."""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return None
        try:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            return (r, g, b, 1.0)
        except ValueError:
            return None
