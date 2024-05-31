import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

log = logging.getLogger("mixit-translator")

logging.basicConfig(level=logging.INFO, format="%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s")


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


class Pronouns(RemoteResource):
    url = "https://api.pronouns.alejo.io/v1/pronouns"
    refresh_max = timedelta(hours=6)

    async def get(self):
        try:
            await self.fetch()
        except NoRefreshException:
            pass
        return self.data


class Users:
    url = "https://api.pronouns.alejo.io/v1/users/{user}"
    users: dict[str, RemoteResource]

    def __init__(self):
        self.users = {}

    async def fetch_user(self, user: str, force: bool = False):
        user = user.lower()
        user_resource = self.users.get(user)
        if user_resource is None:
            user_resource = RemoteResource()
            user_resource.url = self.url.format(user=user)
            self.users[user] = user_resource
        await user_resource.fetch(force=force)
        return user_resource

    async def get_user(self, user: str):
        try:
            user_resource = await self.fetch_user(user)
        except NoRefreshException:
            user_resource = self.users[user.lower()]
        return user_resource.data

    async def flush_users(self):
        log.info("Starting flush_users task")
        while True:
            try:
                await asyncio.sleep(600)
            except asyncio.CancelledError:
                break
            clear_time = datetime.now(tz=timezone.utc) - RemoteResource.refresh_max
            to_clear = [k for k, v in self.users.items() if v.last_refreshed < clear_time]
            for key in to_clear:
                del self.users[key]
            if to_clear:
                log.debug(f"Cleared out {to_clear}")
        log.info("Shutting down flush_users task")

    @staticmethod
    def convert_json(pronouns: dict, user: dict) -> dict:
        if "error" in user:
            raise HTTPException(status_code=404, detail="not_found")
        response = dict(user)
        response["pronoun"] = pronouns[user["pronoun_id"]]
        if user["alt_pronoun_id"]:
            response["alt_pronoun"] = pronouns[user["alt_pronoun_id"]]
        else:
            response["alt_pronoun"] = None

        if response["pronoun"]["singular"]:
            response["display"] = response["pronoun"]["subject"]
        elif response["alt_pronoun"]:
            response["display"] = f'{response["pronoun"]["subject"]}/{response["alt_pronoun"]["subject"]}'
        else:
            response["display"] = f'{response["pronoun"]["subject"]}/{response["pronoun"]["object"]}'

        if response["pronoun"]["singular"] or response["pronoun_id"] == "theythem":
            response["subject"] = "They"
            response["subject_possessive"] = "They're"
            response["object"] = "Them"
        else:
            response["subject"] = response["pronoun"]["subject"]
            response["subject_possessive"] = f"{response['subject']}'s"
            response["object"] = response["pronoun"]["object"]

        return response


PRONOUNS = Pronouns()
USERS = Users()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await PRONOUNS.fetch()  # Grab the pronouns db to start with
    task = asyncio.create_task(USERS.flush_users())

    yield  # Run FastAPI stuff

    task.cancel()
    await task


app = FastAPI(lifespan=lifespan)


class JSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=4, separators=(",", ":")).encode("utf-8")


@app.get("/user/{user}", response_class=JSONResponse)
async def root(user: str):
    async with asyncio.TaskGroup() as tg:
        p_task = tg.create_task(PRONOUNS.get())
        u_task = tg.create_task(USERS.get_user(user))
    return Users.convert_json(p_task.result(), u_task.result())


@app.post("/refresh/pronouns", response_class=PlainTextResponse)
async def post_refresh_pronouns():
    try:
        await PRONOUNS.fetch(force=True)
    except NoRefreshException as e:
        raise HTTPException(status_code=425, detail=str(e))
    return "Successfully refreshed pronouns list"


@app.post("/refresh/user/{user}", response_class=PlainTextResponse)
async def post_refresh_pronouns(user: str):
    try:
        await USERS.fetch_user(user, force=True)
    except NoRefreshException as e:
        raise HTTPException(status_code=425, detail=str(e))
    return f"Successfully refreshed user {user.lower()}"


if __name__ == "__main__":
    import uvicorn

    try:
        uvicorn.run(app, host="0.0.0.0", port=55555)
    except KeyboardInterrupt:
        pass
