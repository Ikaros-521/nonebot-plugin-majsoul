import asyncio
from asyncio import wait_for
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from functools import partial
from io import BytesIO
from multiprocessing import cpu_count
from typing import Sequence

import matplotlib.pyplot as plt
from httpx import HTTPStatusError
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.internal.adapter import Message
from nonebot.internal.matcher import Matcher

from nonebot_plugin_majsoul.errors import BadRequestError
from .data.api import paifuya_api as api
from .data.models.game_record import GameRecord
from .data.models.player_info import PlayerInfo
from .data.models.player_num import PlayerNum
from .data.models.player_rank import PlayerRank, PlayerMajorRank
from .data.models.room_rank import all_four_player_room_rank, all_three_player_room_rank, RoomRank
from .mappers.player_num import map_player_num
from .mappers.player_rank import map_player_rank
from ..interceptors.handle_error import handle_error

_executor = ThreadPoolExecutor(cpu_count())


def make_handler(player_num: PlayerNum):
    async def query_majsoul_pt_plot(matcher: Matcher, event: MessageEvent):
        args = event.get_message().extract_plain_text().split()[1:]

        nickname = args[0]
        if len(nickname) > 15:
            raise BadRequestError("昵称长度超过雀魂最大限制")

        await wait_for(handle_query_majsoul_pt_plot(matcher, nickname, player_num), timeout=15)

    return query_majsoul_pt_plot


query_four_player_majsoul_pt_plot_matcher = on_command("雀魂PT推移图", aliases={"雀魂PT图"})
query_four_player_majsoul_pt_plot_records = make_handler(PlayerNum.four)
query_four_player_majsoul_pt_plot_records = handle_error(query_four_player_majsoul_pt_plot_matcher)(
    query_four_player_majsoul_pt_plot_records)
query_four_player_majsoul_pt_plot_matcher.append_handler(query_four_player_majsoul_pt_plot_records)

query_three_player_majsoul_pt_plot_matcher = on_command("雀魂三麻PT推移图", aliases={"雀魂三麻PT图"})
query_three_player_majsoul_pt_plot_records = make_handler(PlayerNum.three)
query_three_player_majsoul_pt_plot_records = handle_error(query_three_player_majsoul_pt_plot_matcher)(
    query_three_player_majsoul_pt_plot_records)
query_three_player_majsoul_pt_plot_matcher.append_handler(query_three_player_majsoul_pt_plot_records)

_color = {RoomRank.four_player_throne_south: 'r',
          RoomRank.four_player_throne_east: 'r',
          RoomRank.four_player_jade_south: 'g',
          RoomRank.four_player_jade_east: 'g',
          RoomRank.four_player_golden_south: 'y',
          RoomRank.four_player_golden_east: 'y',
          RoomRank.three_player_throne_south: 'r',
          RoomRank.three_player_throne_east: 'r',
          RoomRank.three_player_jade_south: 'g',
          RoomRank.three_player_jade_east: 'g',
          RoomRank.three_player_golden_south: 'y',
          RoomRank.three_player_golden_east: 'y'}


def draw(bio: BytesIO,
         player_num: PlayerNum,
         player: PlayerInfo,
         records: Sequence[GameRecord],
         initial_rank: PlayerRank):
    fig: Figure = plt.figure(facecolor='w', figsize=(16, 10))
    ax: Axes = fig.add_subplot(1, 1, 1)

    ax.text(3, 100, '\n'.join(map_player_rank(initial_rank)), fontsize=15)

    pre_rank, pre_pt, pt, base = initial_rank, 600, 600, 600
    max_rank = initial_rank

    for i, r in enumerate(records):
        for p in r.players:
            if p.id != player.id:
                continue

            rank = p.rank
            max_rank = max(max_rank, rank)

            if pre_rank != rank:
                ax.text(i + 3, 100, '\n'.join(map_player_rank(rank)), fontsize=15)
                ax.vlines(i, 0, max(rank.max_pt, pre_rank.max_pt), color='k')

                base = rank.max_pt // 2
                pt = pre_pt = base

            pt += p.pt * 5 if rank.major_rank == PlayerMajorRank.celestial else p.pt

            ax.plot([i, i + 1], [pre_pt, pt], color='k', lw=1.5)
            ax.fill_between([i, i + 1], [pre_pt, pt], color=_color[r.room_rank], alpha=0.05)
            ax.plot([i, i + 1], [base, base], color='k', lw=1.5)
            ax.plot([i, i + 1], [base * 2, base * 2], color='k', lw=1.5)

            pre_rank, pre_pt = rank, pt

    ax.set_title(f'雀魂段位战PT推移图[{map_player_num(player_num)}]（{player.nickname}）', fontsize=12, pad=5)
    ax.set_xlabel('对局数', fontsize=20)
    ax.set_ylabel('PT', fontsize=20)

    # ax.set_xticks(fontsize=20)
    ax.set_yticks([i * 1000 for i in range(11)], fontsize=20)

    ax.set_xlim(0, len(records))
    ax.set_ylim(0, max_rank.max_pt + 100)

    fig.savefig(bio, format='png')


async def handle_query_majsoul_pt_plot(matcher: Matcher, nickname: str, player_num: PlayerNum):
    if player_num == PlayerNum.four:
        room_rank = all_four_player_room_rank
        initial_rank = PlayerRank.from_code(10301)
    elif player_num == PlayerNum.three:
        room_rank = all_three_player_room_rank
        initial_rank = PlayerRank.from_code(20301)
    else:
        raise ValueError(f"invalid player_num: {player_num}")

    players = await api[player_num].search_player(nickname)
    if len(players) == 0:
        await matcher.send("没有查询到该角色在金之间以上的对局数据呢~")
        return

    player = players[0]

    msg = ""
    if len(players) > 1:
        msg += "查询到多条角色昵称呢~，若输出不是您想查找的昵称，请补全查询昵称。\n"
    msg += f"昵称：{player.nickname}"

    try:
        start_time = datetime.fromisoformat("2010-01-01T00:00:00")
        end_time = datetime.fromtimestamp(player.latest_timestamp, timezone.utc)
        records = []

        while True:
            pending_records = await api[player_num].player_records(
                player.id, start_time, end_time, room_rank, limit=200, descending=True
            )
            records.extend(pending_records)

            if len(pending_records) < 200:
                break

            end_time = pending_records[-1].start_time - timedelta(seconds=1)

        records.reverse()
    except HTTPStatusError as e:
        if e.response.status_code == 404:
            records = []
        else:
            raise e

    if not records:
        await matcher.send("没有查询到该角色在金之间以上的对局数据呢~")
        return

    msg += "\nPS：本数据不包含金之间以下对局以及2019.11.29之前的对局"

    if not records:
        await matcher.send(msg)
    else:
        with BytesIO() as bio:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(_executor, partial(draw, bio, player_num, player, records, initial_rank))

            await matcher.send(Message([
                MessageSegment.text(msg),
                MessageSegment.image(bio)
            ]))