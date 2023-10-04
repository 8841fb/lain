from __future__ import annotations

import logging


class Formatter(logging.Formatter):
    # Codes:
    ansi_1 = "\x1b[38;5;68m"
    ansi_2 = "\x1b[38;5;117m"
    asci_3 = "\x1b[38;5;147m"
    rst = "\x1b[0m"
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    bold_red_underline = "\x1b[31;1;4m"
    reset = "\x1b[0m"
    blue = "\x1b[34m"
    green = "\x1b[32m"
    cyan = "\x1b[36m"

    format = f"{rst}[{ansi_1}%(levelname)s{rst} @ {ansi_2}%(asctime)s{rst}]{rst} ({asci_3}%(name)s{rst}) {rst}%(message)s{rst}"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: yellow + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset,
    }

    def format(self, record):
        logging.getLogger("openai").setLevel(logging.WARNING)
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M")
        return formatter.format(record)
