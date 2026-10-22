import pytest

from njuskalo_mcp.fetcher import BLOCK_HINT, BlockedError, Fetcher


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
    monkeypatch.setattr(fetcher, "_get_session", lambda: _pop(sessions))
    monkeypatch.setattr(fetcher, "_browser_fallback", _no_browser)  # as when the [browser] extra is absent

    with pytest.raises(BlockedError, match="captcha"):
        await fetcher.get("https://www.njuskalo.hr/auti")
    assert challenged.closed and fetcher._session is None

    assert "__INITIAL_STATE__" in await fetcher.get("https://www.njuskalo.hr/auti")


async def _pop(sessions):
    return sessions.pop(0)


async def _no_browser(url):
    raise BlockedError(BLOCK_HINT)
