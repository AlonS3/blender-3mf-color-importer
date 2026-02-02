# SPDX-License-Identifier: MIT
"""
3MF Color Importer - Import slicer .3mf files with paint data as vertex colors.

Supports Bambu Studio, OrcaSlicer, Snapmaker Orca, and other compatible slicers.
"""

bl_info = {
    "name": "3MF Color Importer",
    "author": "Alon Shemer",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "File > Import > 3MF with Colors (.3mf)",
    "description": "Import 3MF files with multicolor paint data as vertex colors (Bambu Studio, OrcaSlicer, Snapmaker Orca)",
    "doc_url": "https://github.com/AlonS3/blender-3mf-color-importer",
    "tracker_url": "https://github.com/AlonS3/blender-3mf-color-importer/issues",
    "category": "Import-Export",
}

import bpy

from .import_operator import IMPORT_OT_bambu_3mf


classes = (
    IMPORT_OT_bambu_3mf,
)


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_bambu_3mf.bl_idname, text="3MF with Colors (.3mf)")


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
