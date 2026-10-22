import pytest

from njuskalo_mcp.fetcher import BlockedError, Fetcher


class FakeResponse:
    def __init__(self, text, url, status_code=200):
        self.text, self.url, self.status_code = text, url, status_code


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.closed = False

    async def get(self, url):
        return self.responses.pop(0)

    async def close(self):
        self.closed = True


async def test_challenged_session_is_discarded(monkeypatch):
    fetcher = Fetcher(min_delay=0)
    challenged = FakeSession([FakeResponse("<form>", "https://validate.perfdrive.com/x/?ssc=njuskalo")])
    fresh = FakeSession([FakeResponse("<script>window.__INITIAL_STATE__={}</script>", "https://www.njuskalo.hr/auti")])
    sessions = [challenged, fresh]

    async def get_session():  # like the real one: create lazily, keep until reset
        if fetcher._session is None:
            fetcher._session = sessions.pop(0)
        return fetcher._session

    monkeypatch.setattr(fetcher, "_get_session", get_session)

    with pytest.raises(BlockedError, match="captcha"):
        await fetcher.get("https://www.njuskalo.hr/auti")
    assert challenged.closed and fetcher._session is None

    assert "__INITIAL_STATE__" in await fetcher.get("https://www.njuskalo.hr/auti")
    assert fetcher._session is fresh
