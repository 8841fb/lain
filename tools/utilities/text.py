from typing import List, Sequence

import random
import string
import urllib.parse
from discord.ext.commands import CommandError
from xxhash import xxh64_hexdigest


def hash(text: str):
    return xxh64_hexdigest(str(text))


def unique_id(lenght: int = 6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=lenght))


def format_uri(text: str):
    return urllib.parse.quote(text, safe="")


class Plural:
    def __init__(self, value: int | List, number: bool = True, code: bool = False):
        self.value: int = len(value) if isinstance(value, list) else value
        self.number: bool = number
        self.code: bool = code

    def __format__(self, format_spec: str) -> str:
        v = self.value
        singular, sep, plural = format_spec.partition("|")
        plural = plural or f"{singular}s"
        if self.number:
            result = f"`{v}` " if self.code else f"{v} "
        else:
            result = ""

        if abs(v) != 1:
            result += plural
        else:
            result += singular

        return result


def shorten(value: str, length: int = 20) -> str:
    if len(value) > length:
        value = value[: length - 2] + (".." if len(value) > length else "").strip()

    return value


def replace_artist(text: str, source: str, output: str):
    return (
        text.replace(f'"artist": "{source}"', f'"artist": "{output}"')
        .replace(f'"name": "{source}"', f'"name": "{output}"')
        .replace(f'"#text": "{source}"', f'"#text": "{output}"')
    )


def human_join(seq: Sequence[str], delim: str = ", ", final: str = "or") -> str:
    size = len(seq)
    if size == 0:
        return ""

    if size == 1:
        return seq[0]

    if size == 2:
        return f"{seq[0]} {final} {seq[1]}"

    return delim.join(seq[:-1]) + f" {final} {seq[-1]}"


def hidden(value: str) -> str:
    return (
        "||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||"
        f" _ _ _ _ _ _ {value}"
    )
