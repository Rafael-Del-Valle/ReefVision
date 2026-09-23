from pathlib import Path

from reefvision.tests.whaledrone import get_whaledrone_root


def test_optional_external_root(monkeypatch, tmp_path):
    monkeypatch.delenv("REEFVISION_WHALEDRONE_ROOT", raising=False)
    assert get_whaledrone_root() is None
    monkeypatch.setenv("REEFVISION_WHALEDRONE_ROOT", str(tmp_path / "missing"))
    assert get_whaledrone_root() is None
    monkeypatch.setenv("REEFVISION_WHALEDRONE_ROOT", str(tmp_path))
    assert get_whaledrone_root() == tmp_path.resolve()
    monkeypatch.setenv("REEFVISION_WHALEDRONE_ROOT", str(Path(__file__).resolve().parent))
    assert get_whaledrone_root() is None
