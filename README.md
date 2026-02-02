# Blender 3MF Color Importer

A Blender addon that imports `.3mf` files from 3D printing slicers with multicolor paint data preserved as vertex colors.

## Supported Slicers

- **Bambu Studio**
- **OrcaSlicer**
- **Snapmaker Orca**
- Other slicers using compatible `paint_color` encoding

## Features

- Import 3MF geometry (vertices, triangles) with correct unit scaling
- Import multicolor paint data as Blender vertex color attributes
- Auto-detect filament colors from slicer project metadata
- Support for 3MF Production Extension (multiple model files)
- Preserve build transforms (object placement)
- Configurable color palette and conflict resolution

## Requirements

- Blender 4.0 or later

## Installation

### Option 1: Download Release (Recommended)
1. Download the latest release `.zip` from [Releases](https://github.com/AlonS3/blender-3mf-color-importer/releases)
2. In Blender, go to **Edit > Preferences > Add-ons**
3. Click **Install...** and select the downloaded `.zip` file
4. Enable the addon by checking the box next to "3MF Color Importer"

### Option 2: Manual Installation
1. Clone or download this repository
2. Copy the `bambu_3mf_importer` folder to your Blender addons directory:
   - **Windows:** `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\`
   - **macOS:** `~/Library/Application Support/Blender/<version>/scripts/addons/`
   - **Linux:** `~/.config/blender/<version>/scripts/addons/`
3. Enable the addon in Blender preferences

## Usage

1. Go to **File > Import > 3MF with Colors (.3mf)**
2. Select your `.3mf` file exported from your slicer
3. Configure import options (optional):
   - **Color Attribute**: Name for the vertex color attribute (default: `slicer_paint`)
   - **Palette Source**: Auto-detect from file or use generated colors
   - **Conflict Resolution**: How to handle vertices shared by differently-colored triangles
   - **Import Build Transforms**: Apply object placement from the 3MF file
4. Click **Import 3MF with Colors**

## Viewing Vertex Colors

After import, to see the vertex colors in the viewport:

### In Viewport
1. Select the imported object
2. Switch to **Vertex Paint** mode, or
3. In **Solid** shading mode, open the shading popover (dropdown arrow next to shading buttons)
4. Set **Color** to **Attribute**

### For Rendering
1. Open the **Shader Editor**
2. Add a **Color Attribute** node (`Shift+A` > Input > Color Attribute)
3. Set it to use `slicer_paint` (or your custom attribute name)
4. Connect it to your shader's Base Color input

## Import Options

### Color Attribute
The name of the vertex color attribute created on the mesh. Default is `slicer_paint`.

### Palette Source
- **Auto**: Reads filament colors from slicer project metadata (`filament_colour` in `project_settings.config`), falls back to generated colors if not found
- **Generated**: Always uses a set of 16 visually distinct colors

### Conflict Resolution
Since slicer paint data is per-triangle but Blender vertex colors are per-vertex, vertices shared by triangles with different colors need a resolution strategy:

- **Majority Vote** (recommended): Uses the most common color among adjacent triangles
- **Lowest Index**: Uses the lowest color index among adjacent triangles

### Import Build Transforms
When enabled, applies the 3MF build transforms as object matrices, preserving the layout from your slicer.

## Technical Details

### Paint Color Encoding

The addon decodes the `paint_color` attribute used by Bambu Studio and compatible slicers:

| Code | Extruder |
|------|----------|
| `0`, `4`, or missing | Extruder 1 (base) |
| `8` | Extruder 2 |
| `0C` | Extruder 3 |
| `1C` | Extruder 4 |
| `2C` | Extruder 5 |
| ... | ... |

For sub-triangle painting (gradient/partial fills), the addon analyzes the encoded string and uses the dominant non-base color.

### 3MF File Structure

3MF files are ZIP archives containing XML model files. The addon supports the 3MF Production Extension used by modern slicers:

```
archive.3mf/
├── 3D/
│   ├── 3dmodel.model          # Root model (may reference others)
│   └── Objects/
│       └── object_*.model     # Actual mesh data with paint_color
├── Metadata/
│   └── project_settings.config  # Contains filament_colour array
└── [Content_Types].xml
```

### Limitations

1. **Vertex vs Face Colors**: Paint data is per-triangle, but stored as per-vertex colors. Sharp color boundaries may blend at shared vertices.

2. **Standard 3MF Colors**: This addon focuses on the slicer-specific `paint_color` attribute. Standard 3MF color groups (`<colorgroup>`, `pid`, `p1/p2/p3`) are not yet supported.

## Troubleshooting

### "No model files found in 3MF archive"
The file may not be a valid 3MF or may be corrupted. Try re-exporting from your slicer.

### Colors don't appear
1. Make sure you're in Vertex Paint mode or have attribute colors enabled in viewport shading
2. Check that the color attribute exists on the mesh (Object Data Properties > Color Attributes)

### Wrong colors / colors don't match slicer
1. Try setting **Palette Source** to **Auto** to read filament colors from the file
2. If colors still don't match, the slicer may use a different encoding - please [open an issue](https://github.com/AlonS3/blender-3mf-color-importer/issues)

### Object is too small/large
The addon applies unit conversion (millimeters to meters by default). If the scale seems wrong, check your slicer's export settings.

## Contributing

Contributions are welcome! Areas that could use improvement:

- Support for additional slicers
- Standard 3MF color group support (`<colorgroup>`, `pid`, `p1/p2/p3`)
- Face-corner color mode option (for sharper boundaries)
- Better filament palette detection

Please feel free to [open an issue](https://github.com/AlonS3/blender-3mf-color-importer/issues) or submit a pull request.

## License

[MIT License](LICENSE)

## Changelog

### v0.1.0
- Initial release
- Support for Bambu Studio, OrcaSlicer, Snapmaker Orca
- Auto-detect filament colors from project metadata
- Configurable vertex color attribute name
- Majority vote and lowest index conflict resolution
- Build transform support
