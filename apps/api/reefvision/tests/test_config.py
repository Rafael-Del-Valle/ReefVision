from pathlib import Path

from reefvision.config import Settings


def test_settings_create_only_configured_test_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "isolated"
    settings = Settings(data_dir=data_dir)

    settings.ensure_directories()

    assert settings.resolved_data_dir == data_dir.resolve()
    assert data_dir.is_dir()


def test_default_database_url_uses_data_directory(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", database_url=None)

    assert settings.resolved_database_url.endswith("/data/reefvision.db")


def test_settings_allow_desktop_web_origins() -> None:
    settings = Settings(web_origin="http://testserver")

    assert "http://testserver" in settings.allowed_web_origins
    assert "https://tauri.localhost" in settings.allowed_web_origins
    assert settings.allowed_web_origin_regex == r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$"
