#!/usr/bin/env python3
"""Hydrate the desktop model catalog from pinned official release assets."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

APPROVED_DOWNLOAD_PREFIX = (
    "https://github.com/ultralytics/assets/releases/download/"
)
SHA256_PREFIX = "sha256:"


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object in {path}")
    return payload


def _release_url(repository: str, tag: str) -> str:
    return f"https://api.github.com/repos/{repository}/releases/tags/{tag}"


def _fetch_release(repository: str, tag: str) -> dict[str, Any]:
    request = urllib.request.Request(
        _release_url(repository, tag),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ReefVision-desktop-catalog-hydrator/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token and not token.isspace():
        request.add_header("Authorization", f"Bearer {token.strip()}")
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"GitHub returned invalid release metadata for {tag}")
    return payload


def _asset_index(payload: dict[str, Any], tag: str) -> dict[str, dict[str, Any]]:
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list):
        raise RuntimeError(f"Release {tag} does not contain an assets list")
    assets: dict[str, dict[str, Any]] = {}
    for raw_asset in raw_assets:
        if not isinstance(raw_asset, dict):
            continue
        name = str(raw_asset.get("name") or "").strip()
        if name:
            assets[name] = dict(raw_asset)
    return assets


def _validated_asset(asset: dict[str, Any], filename: str, tag: str) -> dict[str, Any]:
    if str(asset.get("name") or "") != filename:
        raise RuntimeError(f"Release {tag} returned the wrong asset for {filename}")
    source_url = str(asset.get("browser_download_url") or "")
    expected_url = f"{APPROVED_DOWNLOAD_PREFIX}{tag}/{filename}"
    if source_url != expected_url:
        raise RuntimeError(
            f"Release {tag} returned an unapproved download URL for {filename}"
        )
    digest = str(asset.get("digest") or "").lower()
    if not digest.startswith(SHA256_PREFIX):
        raise RuntimeError(
            f"Release {tag} does not expose a SHA-256 digest for {filename}"
        )
    sha256 = digest.removeprefix(SHA256_PREFIX)
    if len(sha256) != 64 or any(
        character not in "0123456789abcdef" for character in sha256
    ):
        raise RuntimeError(f"Release {tag} returned an invalid SHA-256 for {filename}")
    size_bytes = int(asset.get("size") or 0)
    if size_bytes <= 0:
        raise RuntimeError(f"Release {tag} returned an invalid size for {filename}")
    return {
        "filename": filename,
        "source_url": source_url,
        "revision": tag,
        "sha256": sha256,
        "size_bytes": size_bytes,
    }


def _complete_expected_file(
    entry: dict[str, Any], expected_filename: str
) -> dict[str, Any] | None:
    if (
        entry.get("availability") != "available"
        or entry.get("selection_kind") != "managed_catalog_model"
    ):
        return None
    expected_files = entry.get("expected_files")
    if not isinstance(expected_files, list) or len(expected_files) != 1:
        return None
    expected = expected_files[0]
    if not isinstance(expected, dict):
        return None
    if expected.get("filename") != expected_filename:
        return None
    source_url = str(expected.get("source_url") or "")
    sha256 = str(expected.get("sha256") or "").lower()
    try:
        size_bytes = int(expected.get("size_bytes") or 0)
    except (TypeError, ValueError):
        return None
    if (
        not source_url.startswith(APPROVED_DOWNLOAD_PREFIX)
        or source_url.rsplit("/", 1)[-1] != expected_filename
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or size_bytes <= 0
        or entry.get("expected_checksum") != sha256
        or entry.get("expected_file_size") != size_bytes
        or entry.get("expected_size") != size_bytes
    ):
        return None
    return {
        "filename": expected_filename,
        "source_url": source_url,
        "revision": str(expected.get("revision") or ""),
        "sha256": sha256,
        "size_bytes": size_bytes,
    }


def _release_assets_from_fixture(
    fixture: dict[str, Any],
) -> Callable[[str, str], dict[str, Any]]:
    def load(repository: str, tag: str) -> dict[str, Any]:
        repository_payload = fixture.get(repository)
        if not isinstance(repository_payload, dict):
            raise RuntimeError(f"Release fixture does not contain repository {repository}")
        release = repository_payload.get(tag)
        if not isinstance(release, dict):
            raise RuntimeError(f"Release fixture does not contain tag {tag}")
        return dict(release)

    return load


def hydrate_catalog(
    catalog: dict[str, Any],
    policy: dict[str, Any],
    *,
    release_loader: Callable[[str, str], dict[str, Any]] = _fetch_release,
) -> dict[str, Any]:
    raw_models = catalog.get("models")
    if not isinstance(raw_models, list):
        raise RuntimeError("Model catalog does not contain a models list")
    raw_targets = policy.get("required_models")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise RuntimeError("Desktop model policy has no required_models")
    repository = str(policy.get("repository") or "").strip()
    if repository != "ultralytics/assets":
        raise RuntimeError("Desktop model policy must use ultralytics/assets")
    default_tags = policy.get("release_tags")
    if not isinstance(default_tags, list) or not default_tags:
        raise RuntimeError("Desktop model policy has no release_tags")

    models_by_name: dict[str, dict[str, Any]] = {}
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            continue
        display_name = str(raw_model.get("display_name") or "").strip()
        if display_name:
            if display_name in models_by_name:
                raise RuntimeError(f"Duplicate catalog display name: {display_name}")
            models_by_name[display_name] = raw_model

    releases: dict[str, dict[str, dict[str, Any]]] = {}
    required_ids: list[str] = []
    required_files: list[str] = []
    seen_names: set[str] = set()
    seen_files: set[str] = set()

    for index, raw_target in enumerate(raw_targets):
        if not isinstance(raw_target, dict):
            raise RuntimeError(f"Desktop model target {index} is not an object")
        target = dict(raw_target)
        display_name = str(target.get("display_name") or "").strip()
        filename = str(target.get("filename") or "").strip()
        if not display_name or not filename or Path(filename).name != filename:
            raise RuntimeError(f"Desktop model target {index} is incomplete")
        if display_name in seen_names:
            raise RuntimeError(f"Duplicate desktop model display name: {display_name}")
        if filename in seen_files:
            raise RuntimeError(f"Duplicate desktop model filename: {filename}")
        seen_names.add(display_name)
        seen_files.add(filename)

        entry = models_by_name.get(display_name)
        if entry is None:
            raise RuntimeError(
                f"Desktop model policy references missing catalog entry {display_name}"
            )
        catalog_id = str(entry.get("catalog_id") or "").strip()
        if not catalog_id:
            raise RuntimeError(f"Catalog entry {display_name} has no catalog_id")

        expected = _complete_expected_file(entry, filename)
        if expected is None:
            raw_tags = target.get("release_tags", default_tags)
            if not isinstance(raw_tags, list) or not raw_tags:
                raise RuntimeError(f"No release tags are configured for {display_name}")
            expected = None
            searched_tags: list[str] = []
            for raw_tag in raw_tags:
                tag = str(raw_tag or "").strip()
                if not tag:
                    continue
                searched_tags.append(tag)
                if tag not in releases:
                    releases[tag] = _asset_index(release_loader(repository, tag), tag)
                asset = releases[tag].get(filename)
                if asset is not None:
                    expected = _validated_asset(asset, filename, tag)
                    break
            if expected is None:
                raise RuntimeError(
                    f"Could not find {filename} in releases: {', '.join(searched_tags)}"
                )

            entry["checkpoint_identifier"] = filename
            entry["checkpoint_source"] = "trusted_https_release"
            entry["expected_checksum"] = expected["sha256"]
            entry["expected_file_size"] = expected["size_bytes"]
            entry["download_source_type"] = "trusted_https_release"
            entry["expected_files"] = [expected]
            entry["expected_size"] = expected["size_bytes"]
            entry["desktop_package_status"] = "bundled_installer"
            entry["clean_machine_verification_status"] = "verified_offline_bundle"
            entry["deprecation_status"] = "active"
            entry["installation_state"] = "Not Installed"
            entry["installation_reason"] = (
                "The verified checkpoint is supplied automatically by the desktop installer."
            )
            entry["selection_kind"] = "managed_catalog_model"
            entry["requires_confirmation"] = False
            entry["availability"] = "available"
            entry["model_weight_license"] = str(
                policy.get("model_weight_license")
                or entry.get("model_weight_license")
                or "Official Ultralytics pretrained weights."
            )
            entry["license_summary"] = str(
                policy.get("license_summary")
                or entry.get("license_summary")
                or "Official Ultralytics pretrained weights."
            )
            limitations = entry.get("known_limitations")
            if isinstance(limitations, list):
                entry["known_limitations"] = [
                    str(item)
                    for item in limitations
                    if "packaged-desktop" not in str(item).casefold()
                    and "must be explicitly installed" not in str(item).casefold()
                ]
            for field in (
                "provider",
                "provider_id",
                "provider_version",
                "provider_pack_id",
                "required_provider_pack",
            ):
                if field in target:
                    entry[field] = target[field]

        required_ids.append(catalog_id)
        required_files.append(filename)

    hydrated = dict(catalog)
    hydrated["models"] = raw_models
    hydrated["desktop_bundle_policy_version"] = str(
        policy.get("policy_version") or "1"
    )
    hydrated["desktop_bundle_required_ids"] = sorted(required_ids)
    hydrated["desktop_bundle_required_files"] = sorted(required_files)
    return hydrated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-metadata", type=Path)
    args = parser.parse_args()

    catalog = _load_object(args.catalog.resolve())
    policy = _load_object(args.policy.resolve())
    release_loader = _fetch_release
    if args.release_metadata is not None:
        fixture = _load_object(args.release_metadata.resolve())
        release_loader = _release_assets_from_fixture(fixture)

    hydrated = hydrate_catalog(catalog, policy, release_loader=release_loader)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.write_text(
        json.dumps(hydrated, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(
        "Desktop model catalog hydrated: "
        f"{len(hydrated['desktop_bundle_required_ids'])} required checkpoints."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Desktop model catalog hydration failed: {exc}")
        raise
