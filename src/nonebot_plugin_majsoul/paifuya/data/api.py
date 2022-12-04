from datetime import datetime
from typing import List, AbstractSet

from httpx import AsyncClient, URL
from nonebot import get_driver, logger

from .models.player_info import PlayerInfo
from .models.player_stats import PlayerStats
from .models.room_rank import RoomRank


class AmaeKoromoApi:
    baseurl: str

    def __init__(self):
        async def req_hook(request):
            logger.trace(f"Request: {request.method} {request.url} - Waiting for response")

        async def resp_hook(response):
            request = response.request
            logger.trace(f"Response: {request.method} {request.url} - Status {response.status_code}")
            response.raise_for_status()

        self.client: AsyncClient = AsyncClient(
            event_hooks={'request': [req_hook], 'response': [resp_hook]}
        )

        get_driver().on_shutdown(self.aclose)

    async def aclose(self):
        await self.client.aclose()

    async def search_player(self, nickname: str, *, limit: int = 10) -> List[PlayerInfo]:
        resp = await self.client.get(
            URL(f"{self.baseurl}/search_player/{nickname}"),
            params={"limit": limit}
        )
        return [PlayerInfo.parse_obj(x) for x in resp.json()]

    async def player_stats(self, player_id: int, start_time: datetime, end_time: datetime,
                           room_rank: AbstractSet[RoomRank]) -> PlayerStats:
        start_timestamp = int(start_time.timestamp() * 1000)
        end_timestamp = int(end_time.timestamp() * 1000)
        mode = ".".join(map(lambda x: str(x.value), room_rank))
        resp = await self.client.get(
            URL(f"{self.baseurl}/player_stats/{player_id}/{start_timestamp}/{end_timestamp}"),
            params={"mode": mode}
        )
        return PlayerStats.parse_obj(resp.json())

    async def player_extended_stats(self, player_id: int, start_time: datetime, end_time: datetime,
                                    room_rank: AbstractSet[RoomRank]):
        start_timestamp = int(start_time.timestamp() * 1000)
        end_timestamp = int(end_time.timestamp() * 1000)
        mode = ".".join(map(lambda x: str(x.value), room_rank))
        resp = await self.client.get(
            URL(f"{self.baseurl}/player_extended_stats/{player_id}/{start_timestamp}/{end_timestamp}"),
            params={"mode": mode}
        )
        return resp.json()

    async def player_records(self, player_id: int, start_time: datetime, end_time: datetime,
                             room_rank: AbstractSet[RoomRank], limit: int, descending: bool = True) -> List[dict]:
        start_timestamp = int(start_time.timestamp() * 1000)
        end_timestamp = int(end_time.timestamp() * 1000)
        mode = ".".join(map(lambda x: str(x.value), room_rank))
        resp = await self.client.get(
            URL(f"{self.baseurl}/player_records/{player_id}/{end_timestamp}/{start_timestamp}"),
            params={"mode": mode, "limit": str(limit), "descending": str(descending).lower()}
        )
        return resp.json()


class FourMenAmaeKoromoApi(AmaeKoromoApi):
    baseurl = "https://ak-data-3.sapk.ch/api/v2/pl4"


class ThreeMenAmaeKoromoApi(AmaeKoromoApi):
    baseurl = "https://ak-data-3.sapk.ch/api/v2/pl3"


four_player_api = FourMenAmaeKoromoApi()
three_player_api = ThreeMenAmaeKoromoApi()