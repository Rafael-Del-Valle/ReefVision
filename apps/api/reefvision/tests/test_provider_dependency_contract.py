from __future__ import annotations

from reefvision.ml.dependencies import IMPLEMENTED_PROVIDER_SPECS


def test_implemented_providers_use_single_opencv_contrib_runtime() -> None:
    cv2_requirements = [
        requirement
        for spec in IMPLEMENTED_PROVIDER_SPECS
        for requirement in spec.packages
        if requirement.import_name == "cv2"
    ]

    assert cv2_requirements
    assert all(
        requirement.distribution_name == "opencv-contrib-python" for requirement in cv2_requirements
    )
    assert all(requirement.required_version == "4.12.0.88" for requirement in cv2_requirements)


def test_implemented_provider_specs_do_not_require_conflicting_opencv_wheels() -> None:
    conflicting = {
        "opencv-python",
        "opencv-python-headless",
        "opencv-contrib-python-headless",
    }
    required_distributions = {
        requirement.distribution_name
        for spec in IMPLEMENTED_PROVIDER_SPECS
        for requirement in spec.packages
    }

    assert required_distributions.isdisjoint(conflicting)
    assert "opencv-contrib-python" in required_distributions
