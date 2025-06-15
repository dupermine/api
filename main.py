import asyncio
import random
import string
import json
from typing import Literal

import aiohttp
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from yandex_music import ClientAsync

from classes.Info import Info

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


client_session: aiohttp.ClientSession | None = None


async def get_client_session() -> aiohttp.ClientSession:
    global client_session
    if client_session is None:
        client_session = aiohttp.ClientSession()
    return client_session


def generate_device_id(length: int = 16) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


async def get_info(ya_token: str = Header(..., title="Yandex Music Token")) -> Info:
    client = await ClientAsync(ya_token).init()
    return Info(client)


async def create_ynison_ws(ya_token: str, ws_proto: dict) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(
            "wss://ynison.music.yandex.ru/redirector.YnisonRedirectService/GetRedirectToYnison",
            headers={
                "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(ws_proto)}",
                "Origin": "http://music.yandex.ru",
                "Authorization": f"OAuth {ya_token}",
            },
        ) as ws:
            response = await ws.receive()
            return json.loads(response.data)


@app.get("/song/{track_id}")
async def get_song_by_id(track_id: int, info: Info = Depends(get_info)) -> dict:
    return await info.get_track_by_id(track_id)


@app.get("/songs")
async def get_tracks_by_ids(track_ids: str, info: Info = Depends(get_info)) -> list:
    ids = map(int, track_ids.split(","))
    return [await info.get_track_by_id(track_id) for track_id in ids]


@app.get("/favourite_songs")
async def get_favourite_tracks(
    skip: int = 0, count: int = 25, info: Info = Depends(get_info)
) -> dict:
    return await info.get_favourite_songs(skip, count)


@app.get("/album/{album_id}")
async def get_album_by_id(album_id: int, info: Info = Depends(get_info)) -> dict:
    return await info.get_albums_with_tracks(album_id)


@app.get("/playlist_of_the_day")
async def get_tracks_from_playlist_of_the_day(info: Info = Depends(get_info)) -> list:
    return await info.get_track_playlist_of_day()


@app.get("/search")
async def get_search(request: str, info: Info = Depends(get_info)) -> dict:
    return await info.search(request)


@app.get("/get_track_from_station")
async def get_track_from_station(info: Info = Depends(get_info)) -> dict:
    return await info.get_track_from_station()


@app.get("/new_release")
async def get_new_release(
    skip: int = 0, count: int = 10, info: Info = Depends(get_info)
) -> list:
    return await info.get_new_releases(skip, count)


@app.get("/artist/{artist_id}")
async def get_artist_info(artist_id: int, info: Info = Depends(get_info)) -> dict:
    return await info.get_artist_info(artist_id)


@app.get("/like_track/{track_id}")
async def like_track(track_id: int, info: Info = Depends(get_info)) -> dict:
    return await info.like_track(track_id)


@app.get("/dislike_track/{track_id}")
async def dislike_track(track_id: int, info: Info = Depends(get_info)) -> dict:
    return await info.unlike_track(track_id)


@app.get("/get_current_track_beta")
async def get_current_track_beta(
    info: Info = Depends(get_info),
    ya_token: str = Header(...),
    session: aiohttp.ClientSession = Depends(get_client_session),
) -> dict:
    if ya_token == "<your token>":
        raise HTTPException(400, "Change token!!!")

    device_id = generate_device_id()
    ws_proto = {
        "Ynison-Device-Id": device_id,
        "Ynison-Device-Info": json.dumps({"app_name": "Chrome", "type": 1}),
    }
    data = await create_ynison_ws(ya_token, ws_proto)

    ws_proto["Ynison-Redirect-Ticket"] = data["redirect_ticket"]

    payload = {
        "update_full_state": {
            "player_state": {
                "player_queue": {
                    "current_playable_index": -1,
                    "entity_id": "",
                    "entity_type": "VARIOUS",
                    "playable_list": [],
                    "options": {"repeat_mode": "NONE"},
                    "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                    "version": {
                        "device_id": device_id,
                        "version": 9021243204784341000,
                        "timestamp_ms": 0,
                    },
                    "from_optional": "",
                },
                "status": {
                    "duration_ms": 0,
                    "paused": True,
                    "playback_speed": 1,
                    "progress_ms": 0,
                    "version": {
                        "device_id": device_id,
                        "version": 8321822175199937000,
                        "timestamp_ms": 0,
                    },
                },
            },
            "device": {
                "capabilities": {
                    "can_be_player": True,
                    "can_be_remote_controller": False,
                    "volume_granularity": 16,
                },
                "info": {
                    "device_id": device_id,
                    "type": "WEB",
                    "title": "Chrome Browser",
                    "app_name": "Chrome",
                },
                "volume_info": {"volume": 0},
                "is_shadow": True,
            },
            "is_currently_active": False,
        },
        "rid": "ac281c26-a047-4419-ad00-e4fbfda1cba3",
        "player_action_timestamp_ms": 0,
        "activity_interception_type": "DO_NOT_INTERCEPT_BY_DEFAULT",
    }

    async with session.ws_connect(
        f"wss://{data['host']}/ynison_state.YnisonStateService/PutYnisonState",
        headers={
            "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(ws_proto)}",
            "Origin": "http://music.yandex.ru",
            "Authorization": f"OAuth {ya_token}",
        },
    ) as ws:
        await ws.send_str(json.dumps(payload))
        response = await ws.receive()
        ynison = json.loads(response.data)

    track = ynison["player_state"]["player_queue"]["playable_list"][
        ynison["player_state"]["player_queue"]["current_playable_index"]
    ]

    return {
        "paused": ynison["player_state"]["status"]["paused"],
        "duration_ms": ynison["player_state"]["status"]["duration_ms"],
        "progress_ms": ynison["player_state"]["status"]["progress_ms"],
        "entity_id": ynison["player_state"]["player_queue"]["entity_id"],
        "entity_type": ynison["player_state"]["player_queue"]["entity_type"],
        "track": await info.get_track_by_id(track["playable_id"]),
    }


@app.get("/get_likes_from_username")
async def get_likes_from_username(
    username: str, skip: int = 0, count: int = 10, info: Info = Depends(get_info)
) -> dict:
    return await info.get_like_tracks_by_username(username, skip, count)


@app.get("/play_ynison_track")
async def play_ynison_track(
    ya_token: str = Header(...),
    track_id: int = Header(...),
    session: aiohttp.ClientSession = Depends(get_client_session),
) -> Literal[True]:
    device_id = generate_device_id()
    ws_proto = {
        "Ynison-Device-Id": device_id,
        "Ynison-Device-Info": json.dumps({"app_name": "Chrome", "type": 1}),
    }
    data = await create_ynison_ws(ya_token, ws_proto)

    ws_proto["Ynison-Redirect-Ticket"] = data["redirect_ticket"]

    payload = {
        "update_player_state": {
            "player_state": {
                "player_queue": {
                    "current_playable_index": 0,
                    "entity_id": "",
                    "entity_type": "VARIOUS",
                    "playable_list": [
                        {"playable_id": track_id, "playable_type": "TRACK"}
                    ],
                    "options": {"repeat_mode": "ALL"},
                    "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                    "version": {
                        "device_id": device_id,
                        "version": 3487536190692794400,
                        "timestamp_ms": 0,
                    },
                },
                "status": {
                    "duration_ms": 0,
                    "paused": False,
                    "playback_speed": 1,
                    "progress_ms": 0,
                    "version": {
                        "device_id": device_id,
                        "version": 761129841314803700,
                        "timestamp_ms": 0,
                    },
                },
            }
        }
    }

    async with session.ws_connect(
        f"wss://{data['host']}/ynison_state.YnisonStateService/PutYnisonState",
        headers={
            "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(ws_proto)}",
            "Origin": "http://music.yandex.ru",
            "Authorization": f"OAuth {ya_token}",
        },
    ) as ws:
        await ws.send_str(json.dumps(payload))
    return True


@app.get("/small_joke")
async def lol_kek(ya_token: str = Header(...), info: Info = Depends(get_info)) -> None:
    await play_ynison_track(ya_token, 114422104)
    await info.like_track(114422104)


app.mount("/", StaticFiles(directory="./static/", html=True))


async def main() -> None:
    import uvicorn

    config = uvicorn.Config(app, "0.0.0.0", 8000)
    server = uvicorn.Server(config)

    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
