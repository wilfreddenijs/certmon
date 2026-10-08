from contextlib import nullcontext
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from tests import conftest


def test_readiness_retries_socket_timeouts_and_url_errors(monkeypatch):
    failures = iter([TimeoutError("slow response"), URLError("not ready"), None])

    def request(*args, **kwargs):
        failure = next(failures)
        if failure:
            raise failure
        return nullcontext(SimpleNamespace(status=200))

    monkeypatch.setattr(conftest, "urlopen", request)
    monkeypatch.setattr(conftest.time, "sleep", lambda seconds: None)
    conftest._wait_for_certmon("http://127.0.0.1:1234")


def test_readiness_still_fails_after_deadline(monkeypatch):
    clock = iter([0, 0, 6])
    monkeypatch.setattr(conftest.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(conftest.time, "sleep", lambda seconds: None)

    def timeout(*args, **kwargs):
        raise TimeoutError("not ready")

    monkeypatch.setattr(conftest, "urlopen", timeout)
    with pytest.raises(RuntimeError, match="did not become ready"):
        conftest._wait_for_certmon("http://127.0.0.1:1234")
