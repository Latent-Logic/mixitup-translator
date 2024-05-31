import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from mixitup_translator import pronouns
from mixitup_translator.utils import JSONResponse, NoRefreshException

log = logging.getLogger("mixitup-translator")

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = []
    tasks.extend(await pronouns.startup())

    yield  # Run FastAPI stuff

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks)


app = FastAPI(lifespan=lifespan)


@app.get("/pronouns", response_class=JSONResponse)
async def get_pronouns_about():
    return {
        **pronouns.ABOUT,
        "uris": [
            {"method": "GET", "url": "/pronouns/v1/user/{user}"},
            {"method": "POST", "url": "/pronouns/v1/refresh/pronouns"},
            {"method": "POST", "url": "/pronouns/v1/refresh/user/{user}"},
        ],
    }


@app.get("/pronouns/v1/user/{user}", response_class=JSONResponse)
async def get_pronouns_user(user: str):
    async with asyncio.TaskGroup() as tg:
        p_task = tg.create_task(pronouns.PRONOUNS.get())
        u_task = tg.create_task(pronouns.USERS.get_user(user))
    return pronouns.Users.convert_json(p_task.result(), u_task.result())


@app.post("/pronouns/v1/refresh/pronouns", response_class=PlainTextResponse)
async def post_pronouns_refresh_pronouns():
    try:
        await pronouns.PRONOUNS.fetch(force=True)
    except NoRefreshException as e:
        raise HTTPException(status_code=425, detail=str(e))
    return "Successfully refreshed pronouns list"


@app.post("/pronouns/v1/refresh/user/{user}", response_class=PlainTextResponse)
async def post_pronouns_refresh_user(user: str):
    try:
        await pronouns.USERS.fetch_user(user, force=True)
    except NoRefreshException as e:
        raise HTTPException(status_code=425, detail=str(e))
    return f"Successfully refreshed user {user.lower()}"


if __name__ == "__main__":
    import uvicorn

    try:
        uvicorn.run(app, host="0.0.0.0", port=55555)
    except KeyboardInterrupt:
        pass
