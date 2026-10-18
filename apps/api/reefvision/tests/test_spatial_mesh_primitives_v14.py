from reefvision.services.spatial_mesh_measurements import triangle_area


def test_area():
    assert triangle_area((0, 0, 0), (2, 0, 0), (0, 3, 0)) == 3
