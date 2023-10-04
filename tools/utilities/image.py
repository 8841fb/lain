import asyncio, discord

from io import BytesIO
from math import sqrt

from aiohttp import ClientSession  # circular import
from PIL import Image
from yarl import URL

from .process import async_executor
from .text import unique_id
import imagehash as ih


@async_executor()
def sample_colors(buffer: bytes) -> int:
    color = int(
        "%02x%02x%02x"
        % (
            Image.open(BytesIO(buffer))
            .convert("RGBA")
            .resize((1, 1), resample=0)
            .getpixel((0, 0))
        )[:3],
        16,
    )

    return f"{discord.Color(int(color))}"


@async_executor()
def rotate(image: bytes, degrees: int = 90):
    if isinstance(image, bytes):
        image = BytesIO(image)

    with Image.open(image) as img:
        img = img.convert("RGBA").resize(
            (img.width * 2, img.height * 2),
        )

        img = img.rotate(
            angle=-degrees,
            expand=True,
        )

        buffer = BytesIO()
        img.save(
            buffer,
            format="png",
        )
        buffer.seek(0)

        img.close()
        return buffer


@async_executor()
def image_hash(image: BytesIO):
    if isinstance(image, bytes):
        image = BytesIO(image)

    result = str(ih.average_hash(image=Image.open(image), hash_size=8))
    if result == "0000000000000000":
        return unique_id(16)
    else:
        return result


async def dominant(
    session: ClientSession,
    url: str,
) -> int:
    try:
        buffer = await session.request(
            "GET",
            URL(url),
        )
    except:
        return 0
    else:
        return await sample_colors(buffer)


@async_executor()
def _collage_open(image: BytesIO):
    image = (
        Image.open(image)
        .convert("RGBA")
        .resize(
            (
                256,
                256,
            )
        )
    )
    return image


async def _collage_read(image: str):
    async with ClientSession() as session:
        async with session.get(image) as response:
            try:
                return await _collage_open(BytesIO(await response.read()))
            except:
                return None


async def _collage_paste(image: Image, x: int, y: int, background: Image):
    background.paste(
        image,
        (
            x * 256,
            y * 256,
        ),
    )


async def collage(images: list[str]):
    tasks = list()
    for image in images:
        tasks.append(_collage_read(image))

    images = [image for image in await asyncio.gather(*tasks) if image]
    if not images:
        return None

    rows = int(sqrt(len(images)))
    columns = (len(images) + rows - 1) // rows

    background = Image.new(
        "RGBA",
        (
            columns * 256,
            rows * 256,
        ),
    )
    tasks = list()
    for i, image in enumerate(images):
        tasks.append(_collage_paste(image, i % columns, i // columns, background))
    await asyncio.gather(*tasks)

    buffer = BytesIO()
    background.save(
        buffer,
        format="png",
    )
    buffer.seek(0)

    background.close()
    for image in images:
        image.close()

    return discord.File(
        buffer,
        filename="collage.png",
    )
