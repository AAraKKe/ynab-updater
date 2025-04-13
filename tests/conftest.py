from pathlib import Path

import pytest


@pytest.fixture
def config_file(tmp_path: Path, assets: Path) -> Path:
    config_content = (assets / "config.json").read_text()
    config_path = tmp_path / "config.json"
    config_path.write_text(config_content)
    return config_path


@pytest.fixture
def assets() -> Path:
    return Path(__file__).parent / "assets"
