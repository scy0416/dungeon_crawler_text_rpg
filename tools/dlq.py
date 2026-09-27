# /// script
# requires-python = ">=3.12"
# dependencies = ["redis>=5"]
# ///
"""DLQ(Dead Letter Queue) 운영 도구.

Redis 포트가 호스트에 열려 있어야 한다 (docker-compose.debug.yml 사용):
    docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d

사용법:
    uv run tools/dlq.py list                       # 모든 DLQ 요약
    uv run tools/dlq.py list dungeon.combat_result.dlq
    uv run tools/dlq.py redrive dungeon.combat_result.dlq [--id <entry-id>]
    uv run tools/dlq.py purge dungeon.combat_result.dlq [--id <entry-id>]

redrive는 원본 스트림에 이벤트를 다시 넣는다. 모든 Consumer Group이 다시 받지만
이미 처리한 그룹은 event_id(processed_events)로 건너뛰므로 안전하다.
"""

import argparse
import asyncio
import json
import os

from redis.asyncio import Redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
META_FIELDS = ("original_stream", "original_id", "consumer_group", "error")


async def dlq_streams(redis: Redis) -> list[str]:
    return sorted([key async for key in redis.scan_iter(match="*.dlq", _type="stream")])


async def entries(redis: Redis, dlq: str, entry_id: str | None) -> list[tuple[str, dict[str, str]]]:
    if entry_id:
        return await redis.xrange(dlq, min=entry_id, max=entry_id)
    return await redis.xrange(dlq)


async def cmd_list(redis: Redis, dlq: str | None) -> None:
    streams = [dlq] if dlq else await dlq_streams(redis)
    if not streams:
        print("DLQ가 비어 있습니다.")
    for stream in streams:
        rows = await redis.xrange(stream)
        print(f"== {stream} ({len(rows)}건)")
        for entry_id, fields in rows:
            try:
                event_id = json.loads(fields.get("data", "")).get("event_id")
            except (json.JSONDecodeError, AttributeError):
                event_id = None
            print(f"  {entry_id}  group={fields.get('consumer_group')}  event_id={event_id}")
            print(f"    error: {fields.get('error', '').replace(chr(10), ' ')[:200]}")


async def cmd_redrive(redis: Redis, dlq: str, entry_id: str | None) -> None:
    for dlq_id, fields in await entries(redis, dlq, entry_id):
        original = {k: v for k, v in fields.items() if k not in META_FIELDS}
        new_id = await redis.xadd(fields["original_stream"], original)
        await redis.xdel(dlq, dlq_id)
        print(f"redrive {dlq_id} → {fields['original_stream']} {new_id}")


async def cmd_purge(redis: Redis, dlq: str, entry_id: str | None) -> None:
    ids = [dlq_id for dlq_id, _ in await entries(redis, dlq, entry_id)]
    if ids:
        await redis.xdel(dlq, *ids)
    print(f"purged {len(ids)}건 from {dlq}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="DLQ 운영 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("dlq", nargs="?")
    for name in ("redrive", "purge"):
        p = sub.add_parser(name)
        p.add_argument("dlq")
        p.add_argument("--id", dest="entry_id")
    args = parser.parse_args()

    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        if args.command == "list":
            await cmd_list(redis, args.dlq)
        elif args.command == "redrive":
            await cmd_redrive(redis, args.dlq, args.entry_id)
        else:
            await cmd_purge(redis, args.dlq, args.entry_id)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
