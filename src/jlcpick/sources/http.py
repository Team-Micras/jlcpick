"""HTTP requests shared by the sources: identifiable, paced and with clear errors."""

import json
import math
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from jlcpick import __version__

USER_AGENT = f"jlcpick/{__version__} (+https://github.com/Team-Micras/jlcpick)"
PAUSE_S = 3.0
_last_request: dict[str, float] = {}


class SourceError(Exception):
    """A remote source failed or does not know the requested part."""


def fetch(url: str, body: dict[str, Any] | None = None) -> bytes:
    """GET ``url``, or POST ``body`` as JSON, at most once every ``PAUSE_S`` per site."""
    host = urlsplit(url).netloc
    site = ".".join(host.split(".")[-2:])
    elapsed = time.monotonic() - _last_request.get(site, -math.inf)
    if elapsed < PAUSE_S:
        time.sleep(PAUSE_S - elapsed)
    data = None if body is None else json.dumps(body).encode()
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    try:
        with urlopen(Request(url, data, headers), timeout=30) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 403:
            raise SourceError(
                f"{host} refused the request (HTTP 403): it is rate-limiting this machine,"
                " usually for about 10 minutes; wait and try again."
            ) from error
        raise SourceError(f"{host} answered HTTP {error.code}") from error
    except OSError as error:
        raise SourceError(f"cannot reach {host}: {error}") from error
    finally:
        _last_request[site] = time.monotonic()


def fetch_json(url: str, body: dict[str, Any] | None = None) -> Any:
    """Like `fetch`, decoding the response as JSON."""
    try:
        return json.loads(fetch(url, body))
    except json.JSONDecodeError as error:
        raise SourceError(f"{urlsplit(url).netloc} did not answer JSON") from error
