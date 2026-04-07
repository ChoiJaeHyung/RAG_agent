#!/bin/bash
# 채팅 토큰 발급 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PYTHON="$SCRIPT_DIR/venv/bin/python"
PHONE="${1:-01029270423}"
DOMAIN="${2:-https://8b02fafdbd9d.ngrok-free.app}"

"$PYTHON" -c "
import asyncio
import aiomysql
import secrets
from datetime import datetime, timedelta

async def generate_token():
    pool = await aiomysql.create_pool(
        host='127.0.0.1',
        port=9443,
        user='rsup',
        password='rsup#EDC3900',
        db='r_agent_db',
        autocommit=True
    )

    phone = '$PHONE'
    token = secrets.token_hex(4)
    expires_at = datetime.now() + timedelta(hours=24)

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'INSERT INTO chat_tokens (token, phone, expires_at) VALUES (%s, %s, %s)',
                (token, phone, expires_at)
            )

    pool.close()
    await pool.wait_closed()

    print(f'Token: {token}')
    print(f'Phone: {phone}')
    print(f'Expires: {expires_at}')
    print(f'URL: $DOMAIN/static/chat.html?token={token}')

asyncio.run(generate_token())
"
