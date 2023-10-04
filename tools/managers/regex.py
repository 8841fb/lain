from re import IGNORECASE, compile

DISCORD_MESSAGE = compile(
    r"(?:https?://)?(?:canary\.|ptb\.|www\.)?discord(?:app)?.(?:com/channels|gg)/(?P<guild_id>[0-9]{17,22})/(?P<channel_id>[0-9]{17,22})/(?P<message_id>[0-9]{17,22})"
)
TIME = compile(r"(?P<time>\d+)(?P<unit>[smhdw])")
TIME_HHMMSS = compile(r"(?P<h>\d{1,2}):(?P<m>\d{1,2}):(?P<s>\d{1,2})")
TIME_SS = compile(r"(?P<m>\d{1,2}):(?P<s>\d{1,2})")
TIME_HUMAN = compile(r"(?:(?P<m>\d+)\s*m\s*)?(?P<s>\d+)\s*[sm]")
TIME_OFFSET = compile(r"(?P<s>(?:\-|\+)\d+)\s*s", IGNORECASE)

TWITTER_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www\.)?twitter\.com\/(?P<screen_name>[a-zA-Z0-9_-]+)\/status\/(?P<id>\d+)"
)
URL = compile(r"(?:http\:|https\:)?\/\/[^\s]*")
TIKTOK_DESKTOP_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www\.)?tiktok\.com\/@.*\/video\/\d+"
)
TIKTOK_MOBILE_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www|vm|vt|m).tiktok\.com\/(?:t/)?(\w+)"
)
PINTEREST_PIN_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www\.)?pinterest\.com\/pin\/(?P<id>[0-9]+)"
)
PINTEREST_PIN_APP_URL = compile(r"(?:http\:|https\:)?\/\/pin\.it\/(?P<id>[a-zA-Z0-9]+)")
IMAGE_URL = compile(r"(?:http\:|https\:)?\/\/.*\.(?P<mime>png|jpg|jpeg|webp|gif)")
MEDIA_URL = compile(
    r"(?:http\:|https\:)?\/\/.*\.(?P<mime>mp3|mp4|mpeg|mpga|m4a|wav|mov|webm)"
)
DISCORD_ATTACHMENT = compile(
    r"(https://|http://)?(cdn\.|media\.)discord(app)?\.(com|net)/(attachments|avatars|icons|banners|splashes)/[0-9]{17,22}/([0-9]{17,22}/(?P<filename>.{1,256})|(?P<hash>.{32}))\.(?P<mime>[0-9a-zA-Z]{2,4})?"
)

PERCENTAGE = compile(r"(?P<percentage>\d+)%")
YOUTUBE_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www\.)?youtube\.com\/watch\?v=(?P<id>[a-zA-Z0-9_-]+)"
)
YOUTUBE_SHORT_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www\.)?youtu\.be\/(?P<id>[a-zA-Z0-9_-]+)"
)
YOUTUBE_SHORTS_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www\.)?youtube\.com\/shorts\/(?P<id>[a-zA-Z0-9_-]+)"
)
YOUTUBE_CLIP_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www\.)?youtube\.com\/clip\/Ug(?P<id>[a-zA-Z0-9_-]+)"
)

BITRATE = compile(r"(?P<bitrate>\d+)kbps")
DISCORD_ROLE_MENTION = compile(r"<@&(\d+)>")
DISCORD_ID = compile(r"(\d+)")
DISCORD_EMOJI = compile(r"<(?P<animated>a)?:(?P<name>[a-zA-Z0-9_]+):(?P<id>\d+)>")
DISCORD_USER_MENTION = compile(r"<@?(\d+)>")
DISCORD_INVITE = compile(
    r"(?:https?://)?discord(?:app)?.(?:com/invite|gg)/[a-zA-Z0-9]+/?"
)
STRING = compile(r"[a-zA-Z0-9 ]+")


class Position:
    HH_MM_SS = compile(r"(?P<h>\d{1,2}):(?P<m>\d{1,2}):(?P<s>\d{1,2})")
    MM_SS = compile(r"(?P<m>\d{1,2}):(?P<s>\d{1,2})")
    HUMAN = compile(r"(?:(?P<m>\d+)\s*m\s*)?(?P<s>\d+)\s*[sm]")
    OFFSET = compile(r"(?P<s>(?:\-|\+)\d+)\s*s")


INSTAGRAM_URL = compile(
    r"(?:http\:|https\:)?\/\/(?:www\.)?instagram\.com\/(?:p|tv|reel|reels)\/(?P<shortcode>[a-zA-Z0-9_-]+)\/*"
)


MEDAL_URL = compile("https://medal\.tv/games/(\S*?)/clips/([^\s?]*)/")
