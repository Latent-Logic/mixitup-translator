import json
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from fastapi.responses import JSONResponse as FlatJSONResponse

log = logging.getLogger(__name__)


class NoRefreshException(Exception):
    pass


class RemoteResource:
    refresh_min: timedelta = timedelta(minutes=1)
    refresh_max: timedelta = timedelta(hours=1)
    last_refreshed: datetime = datetime.fromisoformat("2020-01-01T01:01:01-00:00")
    data: dict
    url: str

    def __init__(self):
        self.data = {}

    def _should_refresh(self, force: bool = False):
        age = datetime.now(tz=timezone.utc) - self.last_refreshed
        if age > self.refresh_max:
            return True
        if force and age > self.refresh_min:
            log.info(f"Force refreshing {self.url}")
            return True
        raise NoRefreshException(f"Not refreshing, data is {age} old")

    async def fetch(self, force: bool = False):
        self._should_refresh(force)
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url) as resp:
                if resp.status == 404:
                    self.data = {"error": 404}
                    self.last_refreshed = datetime.now(tz=timezone.utc)
                    return
                resp.raise_for_status()
                self.data = await resp.json()
                self.last_refreshed = datetime.now(tz=timezone.utc)


class JSONResponse(FlatJSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=4, separators=(",", ":")).encode("utf-8")
