import pytest

from reefvision.services.spatial_mesh_measurements import triangle_area


def test_area():
    assert triangle_area((0, 0, 0), (2, 0, 0), (0, 3, 0)) == 3


def test_degenerate_triangle():
    assert triangle_area((0, 0, 0), (1, 1, 1), (2, 2, 2)) == 0


def test_nonfinite_coordinate():
    with pytest.raises(ValueError, match="finite"):
        triangle_area((0, 0, 0), (1, 0, 0), (float("nan"), 1, 0))
