import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from mixitup_translator.utils import NoRefreshException, RemoteResource

log = logging.getLogger(__name__)

_example_pronouns = {
    "any": {"name": "any", "subject": "Any", "object": "Any", "singular": True},
    "hehim": {"name": "hehim", "subject": "He", "object": "Him", "singular": False},
    "other": {"name": "other", "subject": "Other", "object": "Other", "singular": True},
    "theythem": {"name": "theythem", "subject": "They", "object": "Them", "singular": False},
}

_example_user_1 = {
    "channel_id": "123456789",
    "channel_login": "user1",
    "pronoun_id": "hehim",
    "alt_pronoun_id": "any",
}

_example_user_2 = {
    "channel_id": "2345567890",
    "channel_login": "user2",
    "pronoun_id": "other",
    "alt_pronoun_id": None,
}


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
        response["display_lower"] = response["display"].lower()
        response["display_upper"] = response["display"].upper()

        if response["pronoun"]["singular"] or response["pronoun_id"] == "theythem":
            response["subject"] = "They"
            response["subject_possessive"] = "They're"
            response["object"] = "Them"
        else:
            response["subject"] = response["pronoun"]["subject"]
            response["subject_possessive"] = f"{response['subject']}'s"
            response["object"] = response["pronoun"]["object"]
        response["subject_lower"] = response["subject"].lower()
        response["subject_possessive_lower"] = response["subject_possessive"].lower()
        response["object_lower"] = response["object"].lower()

        return response


PRONOUNS = Pronouns()
USERS = Users()

ABOUT = {
    "description": "Load, cache, and format 3rd party twitch user pronoun data",
    "webpage": "https://pr.alejo.io/",
    "APIs used": [Pronouns.url, Users.url],
}


async def startup() -> list:
    await PRONOUNS.fetch()  # Grab the pronouns db to start with
    task = asyncio.create_task(USERS.flush_users())
    return [task]
