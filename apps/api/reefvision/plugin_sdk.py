"""Author a portable, offline ReefVision image-measurement package."""

import base64
import hashlib
from typing import Literal

from reefvision.schemas.plugins import PluginManifest, PluginPackage


def build_rgb_plugin(
    module: bytes,
    *,
    plugin_id: str,
    version: str,
    display_name: str,
    description: str,
    license: str,
    quantity: str,
    unit: Literal["1", "%"],
) -> PluginPackage:
    """Package compiled WebAssembly that follows the RGB summary measurement ABI."""
    manifest = PluginManifest(
        manifest_version=2,
        abi="reefvision.rgb-summary/1",
        plugin_id=plugin_id,
        version=version,
        display_name=display_name,
        description=description,
        license=license,
        permissions=["read_image_rgb_summary"],
        quantity=quantity,
        unit=unit,
        module_sha256=hashlib.sha256(module).hexdigest(),
    )
    package = PluginPackage(
        manifest=manifest, module_base64=base64.b64encode(module).decode("ascii")
    )
    package.module_bytes()
    return package
