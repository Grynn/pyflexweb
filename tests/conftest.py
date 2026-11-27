"""Test-wide safety net: no test may open the real pyflexweb data directory."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Point every default data-dir lookup at a per-test temp dir.

    Tests that patch platformdirs themselves still win (their patch is applied
    later, inside the test).
    """
    monkeypatch.delenv("PYFLEXWEB_DATA_DIR", raising=False)
    data_dir = tmp_path / "pyflexweb-data"
    monkeypatch.setattr("platformdirs.user_data_dir", lambda *a, **k: str(data_dir))
    monkeypatch.setattr("platformdirs.site_data_dir", lambda *a, **k: str(data_dir))
