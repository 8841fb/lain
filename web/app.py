import sys

sys.path.append("/home/vampire/lain/")

import asyncio
from random import randint
from os import listdir

from discord.ext.ipc import Client
from quart import Quart, jsonify, render_template, request

_IPC = Client(
    secret_key="lain",
    standard_port=42069,
    do_multicast=False,
)

app = Quart(
    __name__, subdomain_matching=True, static_url_path="", static_folder="static"
)
app.config["SERVER_NAME"] = "lains.life"


@app.route("/commands")
@app.route("/help")
@app.route("/cmds")
async def commands():
    data = await _IPC.request("commands")
    return await render_template(
        "commands.html", bot=data.response["bot"], commands=data.response["commands"]
    )


@app.route("/avatars/<int:user_id>")
async def avatars(user_id):
    data = await _IPC.request("avatars", user_id=user_id)
    if error := data.response.get("error"):
        raise ValueError(error)

    return await render_template(
        "avatars.html",
        data=data.response,
    )


@app.route("/")
async def index():
    return await render_template(str(randint(1, 5)) + ".html")


@app.errorhandler(Exception)
async def error_handler(error):
    print(error)
    status = error.args[1] if len(error.args) > 1 else 400
    return (
        jsonify(
            {
                "error": f"{status}: Bad Request",
                "message": (
                    error.args[0]
                    if len(error.args) > 0
                    else "An unknown error occurred."
                ),
            }
        ),
        status,
    )


@app.errorhandler(404)
async def not_found(error):
    return (
        jsonify(
            {
                "error": "404: Not Found",
                "message": "The requested resource could not be found.",
            }
        ),
        404,
    )


@app.errorhandler(405)
async def invalid_method(error):
    return (
        jsonify(
            {
                "error": "405: Invalid method",
                "message": f"The requested resource doesn't support the {request.method} method.",
            }
        ),
        405,
    )


@app.errorhandler(500)
async def internal_server_error(error):
    return (
        jsonify(
            {
                "error": "500: Internal Server Error",
                "message": "An internal server error occurred.",
            }
        ),
        500,
    )


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(loop)

    for route in listdir("/home/vampire/lain/web/routes/"):
        if route.endswith(".py"):
            router = __import__(f"routes.{route[:-3]}", fromlist=["*"]).router
            router.app = app
            app.register_blueprint(router)
            print(f"Registered {route[:-3]}")
    try:
        app.run(host="0.0.0.0", port=8080, debug=False, loop=loop)
    except KeyboardInterrupt:
        print("Shutting down...")
        loop.close()


if __name__ == "__main__":
    app.run()
