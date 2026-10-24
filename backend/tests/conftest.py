import pytest
from app.agents import runtime


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("COUNCIL_MOCK_LLM", "1")
    # Crawled pages, verification results and the decision database live in the data folder:
    # every test starts from an empty one, so results never depend on what was crawled locally.
    monkeypatch.setenv("COUNCIL_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    runtime.clear_mocks()
    yield
    runtime.clear_mocks()
