import os
from asyncio import wait_for, create_subprocess_shell, subprocess
from orjson import loads, JSONDecodeError

from datetime import timedelta
from tempfile import TemporaryDirectory
from aiofiles import open as async_open

from tools.managers import ClientSession, cache
from tools.models.shazam import Song
from tools.managers.regex import MEDIA_URL
from tools.utilities.text import hash


@cache(ttl=timedelta(minutes=60), key="{url}")
async def song(session: ClientSession, url: str) -> None:
    """Get a song from a URL"""

    media = MEDIA_URL.match(url)
    if not media:
        raise ValueError("Invalid Media URL.")

    response = await session.request("GET", url)
    if not response:
        raise ValueError("Invalid URL.")

    with TemporaryDirectory() as temp_dir:
        temp_file = os.path.join(temp_dir, f"file" + hash(url) + media.group("mime"))

        async with async_open(temp_file, "wb") as file:
            await file.write(response)

        try:
            songrec = await wait_for(
                create_subprocess_shell(
                    f'songrec audio-file-to-recognized-song "{temp_file}"',
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ),
                timeout=7,
            )
            stdout, stderr = await songrec.communicate()
        except TimeoutError:
            raise ValueError("Timed out, couldn't recognize song.")

        try:
            song = loads(stdout)
        except JSONDecodeError:
            raise ValueError("Couldn't recognize song.")

        if track := song.get("track", {}):
            return Song(
                title=track.get("title"),
                url=track.get("url"),
                artist=track.get("subtitle"),
            )

        raise ValueError("Couldn't recognize song.")
