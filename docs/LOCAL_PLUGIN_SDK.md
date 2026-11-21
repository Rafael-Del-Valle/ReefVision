# Local measurement plugins

Open a project and choose **Models & AI → Plugins and providers**. Select a local `.rvplugin.json` package. Inspect its version, license and requested permission, then enable the version you want to use. Select an imported image to save a measurement. Its history preserves the value, unit, original image checksum, package and module checksums, and the input statistics used. Every measurement starts with unassessed QC.

## Author a package

The version 2 manifest supports the `reefvision.rgb-summary/1` ABI. It supplies mean red, green and blue intensities from the original image, followed by the pixel count. The channel values use the encoded 8-bit RGB scale from 0 to 255. Alpha is ignored, grayscale is expanded to RGB, and palette entries resolve to RGB. The host requires an 8-bit grayscale, palette, RGB or RGBA source and preserves its original bytes. The image summary has no sensor calibration or linear-light interpretation.

Export a WebAssembly function named `measure` with parameters `(f64, f64, f64, i64)` and one finite `f64` result. Declare a quantity and a unit of `1` or `%`. The runtime runs the module in a separate process, provides only the four numeric inputs, and applies execution and memory limits. A trap or interrupted execution leaves the project open. The host rejects imports and modules over 256 KiB. Versions use three numeric components.

This example builds the green intensity fraction package from its accompanying WebAssembly text. Run it from the repository root in an environment containing ReefVision and its Wasmtime dependency.

```python
from pathlib import Path
from wasmtime import wat2wasm
from reefvision.plugin_sdk import build_rgb_plugin

directory = Path("examples/plugins")
module = bytes(wat2wasm((directory / "green-fraction.wat").read_text(encoding="utf-8")))
package = build_rgb_plugin(
    module,
    plugin_id="green_fraction",
    version="1.0.0",
    display_name="Green intensity fraction",
    description="Mean green intensity divided by the 8-bit channel maximum.",
    license="AGPL-3.0-only",
    quantity="green_fraction",
    unit="1",
)
(directory / "green-fraction.rvplugin.json").write_text(
    package.model_dump_json(indent=2) + "\n", encoding="utf-8"
)
```

Each package digest covers the canonical manifest including the SHA-256 of its compiled module. Installing the same bytes again preserves the version's enabled state. To change a published version's contents, give the new package its own version number. A saved workflow keeps the exact package digest and original image digest. To replay it on another machine, install and enable that package locally. Disabled versions retain their measurements and remain identifiable in saved graphs.
