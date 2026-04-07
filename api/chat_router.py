"""
Chat API Router - 웹 채팅 API 엔드포인트
Phase 2: 토큰 검증, 세션 관리, 메시지 처리, 콜백 요청
"""

import asyncio
import uuid
import httpx
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel, Field

from config.settings import settings
from utils.logger import logger
from agents.async_search_agent import AsyncSearchAgent

# ===========================================
# Pydantic Models
# ===========================================

class TokenVerifyResponse(BaseModel):
    """토큰 검증 응답"""
    valid: bool
    session_id: Optional[str] = None
    phone_number: Optional[str] = None  # Frontend expects phone_number
    message: str
    expires_in_hours: Optional[float] = None
    callback_trigger_count: int = 5  # Frontend needs this


class ChatMessage(BaseModel):
    """채팅 메시지"""
    role: str  # user, assistant, system
    content: str
    timestamp: datetime
    confidence: Optional[float] = None
    sources: Optional[List[dict]] = None


class SendMessageRequest(BaseModel):
    """메시지 전송 요청"""
    session_id: str
    message: str


class SendMessageResponse(BaseModel):
    """메시지 전송 응답"""
    success: bool
    session_id: str
    user_message: ChatMessage
    assistant_message: Optional[ChatMessage] = None
    message_count: int
    show_callback_button: bool = False
    error: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    """채팅 히스토리 응답"""
    session_id: str
    phone: str
    message_count: int
    messages: List[ChatMessage]
    status: str
    show_callback_button: bool = False
    created_at: datetime


class CallbackRequest(BaseModel):
    """콜백 요청"""
    session_id: str


class CallbackResponse(BaseModel):
    """콜백 응답"""
    success: bool
    callback_id: Optional[int] = None
    message: str
    phone: Optional[str] = None


class EndSessionRequest(BaseModel):
    """세션 종료 요청"""
    session_id: str
    reason: str = "user_ended"  # user_ended, timeout, etc.


class EndSessionResponse(BaseModel):
    """세션 종료 응답"""
    success: bool
    message: str


# ===========================================
# Database Helper (MariaDB)
# ===========================================

import aiomysql

_db_pool = None

async def get_db_pool():
    """Get or create database connection pool."""
    global _db_pool
    if _db_pool is None:
        _db_pool = await aiomysql.create_pool(
            host=settings.LEARNING_DB_HOST,
            port=int(settings.LEARNING_DB_PORT),
            user=settings.LEARNING_DB_USER,
            password=settings.LEARNING_DB_PASSWORD,
            db=settings.LEARNING_DB_NAME,
            charset='utf8mb4',
            autocommit=True,
            minsize=1,
            maxsize=10
        )
    return _db_pool


async def close_db_pool():
    """Close database connection pool."""
    global _db_pool
    if _db_pool:
        _db_pool.close()
        await _db_pool.wait_closed()
        _db_pool = None


# ===========================================
# Helper: 외부 서버로 세션 데이터 전송
# ===========================================

async def send_session_to_external(
    session: dict,
    messages: list,
    callback_requested: bool = False,
    end_reason: str = "user_ended"
) -> bool:
    """
    세션 데이터를 외부 서버로 전송
    - callback_requested: 콜백 요청 여부
    - end_reason: 종료 사유 (user_ended, timeout, callback_requested)
    """
    external_url = getattr(settings, 'EXTERNAL_CALLBACK_URL', None)
    if not external_url:
        return False

    try:
        # Q&A 쌍으로 대화 내역 묶기
        qa_pairs = []
        turn = 0
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg['role'] == 'user':
                turn += 1
                qa = {
                    "turn": turn,
                    "question": msg['content'],
                    "question_time": msg['created_at'].isoformat() if msg['created_at'] else None,
                    "answer": None,
                    "answer_time": None,
                    "confidence": None
                }
                if i + 1 < len(messages) and messages[i + 1]['role'] == 'assistant':
                    ans = messages[i + 1]
                    qa["answer"] = ans['content']
                    qa["answer_time"] = ans['created_at'].isoformat() if ans['created_at'] else None
                    qa["confidence"] = float(ans['rag_confidence']) if ans['rag_confidence'] else None
                    i += 1
                qa_pairs.append(qa)
            i += 1

        payload = {
            "phone": session['phone'],
            "callback_requested": callback_requested,
            "end_reason": end_reason,
            "requested_at": datetime.now().isoformat(),
            "session_info": {
                "session_id": session['session_id'],
                "started_at": session['created_at'].isoformat() if session['created_at'] else None,
                "total_turns": turn
            },
            "conversation": qa_pairs,
            "metadata": {
                "token": session.get('token')
            }
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(external_url, json=payload)

            if response.status_code < 400:
                logger.info(f"Session data sent to external server: {session['session_id']}")
                return True
            else:
                logger.warning(f"External server returned {response.status_code}")
                return False

    except Exception as e:
        logger.error(f"Failed to send session to external server: {e}")
        return False


# ===========================================
# Router
# ===========================================

router = APIRouter(prefix="/chat", tags=["Chat"])


# ===========================================
# Dependency: Get Search Agent
# ===========================================

_agent: Optional[AsyncSearchAgent] = None

async def get_agent() -> AsyncSearchAgent:
    """Get the search agent singleton."""
    global _agent
    if _agent is None:
        _agent = AsyncSearchAgent()
    return _agent


# ===========================================
# Endpoints
# ===========================================

@router.get("/verify", response_model=TokenVerifyResponse)
async def verify_token(token: str = Query(..., description="채팅 토큰")):
    """
    토큰 검증 및 세션 생성

    - 토큰 유효성 검사 (존재, 만료, 사용여부)
    - 유효하면 채팅 세션 생성
    - 세션 ID 반환
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 1. 토큰 조회
            await cur.execute("""
                SELECT id, token, phone, status, expires_at, call_unique_id
                FROM chat_tokens
                WHERE token = %s
            """, (token,))
            token_row = await cur.fetchone()

            if not token_row:
                return TokenVerifyResponse(
                    valid=False,
                    message="유효하지 않은 토큰입니다."
                )

            # 2. 상태 확인
            if token_row['status'] == 'used':
                # 이미 사용된 토큰 - 기존 세션 조회
                await cur.execute("""
                    SELECT session_id, status FROM chat_sessions
                    WHERE token_id = %s ORDER BY id DESC LIMIT 1
                """, (token_row['id'],))
                session_row = await cur.fetchone()

                if session_row and session_row['status'] == 'active':
                    return TokenVerifyResponse(
                        valid=True,
                        session_id=session_row['session_id'],
                        phone_number=token_row['phone'],
                        message="기존 세션으로 연결됩니다.",
                        callback_trigger_count=settings.CALLBACK_TRIGGER_COUNT
                    )
                else:
                    return TokenVerifyResponse(
                        valid=False,
                        message="이미 종료된 채팅입니다."
                    )

            if token_row['status'] == 'expired':
                return TokenVerifyResponse(
                    valid=False,
                    message="만료된 토큰입니다."
                )

            if token_row['status'] == 'revoked':
                return TokenVerifyResponse(
                    valid=False,
                    message="취소된 토큰입니다."
                )

            # 3. 만료 시간 확인
            if token_row['expires_at'] < datetime.now():
                await cur.execute("""
                    UPDATE chat_tokens SET status = 'expired' WHERE id = %s
                """, (token_row['id'],))
                return TokenVerifyResponse(
                    valid=False,
                    message="만료된 토큰입니다."
                )

            # 4. 토큰 사용 처리 및 세션 생성
            session_id = str(uuid.uuid4())

            await cur.execute("""
                UPDATE chat_tokens
                SET status = 'used', used_at = NOW()
                WHERE id = %s
            """, (token_row['id'],))

            await cur.execute("""
                INSERT INTO chat_sessions
                (session_id, token_id, phone, status)
                VALUES (%s, %s, %s, 'active')
            """, (session_id, token_row['id'], token_row['phone']))

            # 만료까지 남은 시간
            expires_in = (token_row['expires_at'] - datetime.now()).total_seconds() / 3600

            logger.info(f"Chat session created: {session_id} for phone {token_row['phone']}")

            return TokenVerifyResponse(
                valid=True,
                session_id=session_id,
                phone_number=token_row['phone'],
                message="채팅을 시작합니다.",
                expires_in_hours=round(expires_in, 1),
                callback_trigger_count=settings.CALLBACK_TRIGGER_COUNT
            )


@router.post("/message", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    agent: AsyncSearchAgent = Depends(get_agent)
):
    """
    메시지 전송 및 AI 응답

    - 사용자 메시지 저장
    - RAG API 호출
    - AI 응답 저장 및 반환
    - 5회 이상 응답 시 콜백 버튼 표시
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 1. 세션 조회
            await cur.execute("""
                SELECT cs.id, cs.session_id, cs.phone, cs.message_count,
                       cs.status, cs.rag_session_id
                FROM chat_sessions cs
                WHERE cs.session_id = %s
            """, (request.session_id,))
            session = await cur.fetchone()

            if not session:
                raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

            if session['status'] != 'active':
                raise HTTPException(status_code=400, detail="종료된 세션입니다.")

            # 2. 사용자 메시지 저장
            now = datetime.now()
            await cur.execute("""
                INSERT INTO chat_messages
                (chat_session_id, role, content, created_at)
                VALUES (%s, 'user', %s, %s)
            """, (session['id'], request.message, now))

            user_msg = ChatMessage(
                role="user",
                content=request.message,
                timestamp=now
            )

            # 3. RAG API 호출 (고객용 모드)
            try:
                rag_result = await agent.search(
                    question=request.message,
                    session_id=session['rag_session_id'] or request.session_id,
                    max_iterations=3,
                    debug=False,
                    customer_mode=True  # 고객용: 문서참조 없이 친절한 답변
                )

                assistant_content = rag_result.get('answer', '죄송합니다. 응답을 생성하지 못했습니다.')
                confidence = rag_result.get('confidence', 0.5)
                sources = rag_result.get('sources', [])
                rag_session_id = rag_result.get('session_id', request.session_id)

                # rag_session_id 업데이트
                if not session['rag_session_id']:
                    await cur.execute("""
                        UPDATE chat_sessions SET rag_session_id = %s WHERE id = %s
                    """, (rag_session_id, session['id']))

            except Exception as e:
                logger.error(f"RAG API error: {e}")
                assistant_content = "죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                confidence = 0.0
                sources = []

            # 4. AI 응답 저장
            assistant_time = datetime.now()
            await cur.execute("""
                INSERT INTO chat_messages
                (chat_session_id, role, content, rag_confidence, rag_sources, created_at)
                VALUES (%s, 'assistant', %s, %s, %s, %s)
            """, (
                session['id'],
                assistant_content,
                confidence,
                str(sources) if sources else None,
                assistant_time
            ))

            assistant_msg = ChatMessage(
                role="assistant",
                content=assistant_content,
                timestamp=assistant_time,
                confidence=confidence,
                sources=sources[:3] if sources else None  # 상위 3개만
            )

            # 5. 메시지 카운트 업데이트
            new_count = session['message_count'] + 2  # user + assistant
            await cur.execute("""
                UPDATE chat_sessions
                SET message_count = %s,
                    user_message_count = user_message_count + 1,
                    bot_message_count = bot_message_count + 1,
                    updated_at = NOW()
                WHERE id = %s
            """, (new_count, session['id']))

            # 6. 콜백 버튼 표시 여부 (CALLBACK_TRIGGER_COUNT 이상)
            show_callback = (new_count // 2) >= settings.CALLBACK_TRIGGER_COUNT

            logger.info(f"Message processed: session={request.session_id}, count={new_count}")

            return SendMessageResponse(
                success=True,
                session_id=request.session_id,
                user_message=user_msg,
                assistant_message=assistant_msg,
                message_count=new_count,
                show_callback_button=show_callback
            )


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    """
    채팅 히스토리 조회

    - 세션의 모든 메시지 조회
    - 시간순 정렬
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 세션 조회
            await cur.execute("""
                SELECT id, session_id, phone, message_count, status, created_at
                FROM chat_sessions
                WHERE session_id = %s
            """, (session_id,))
            session = await cur.fetchone()

            if not session:
                raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

            # 메시지 조회
            await cur.execute("""
                SELECT role, content, rag_confidence, rag_sources, created_at
                FROM chat_messages
                WHERE chat_session_id = %s
                ORDER BY created_at ASC
            """, (session['id'],))
            messages = await cur.fetchall()

            chat_messages = [
                ChatMessage(
                    role=m['role'],
                    content=m['content'],
                    timestamp=m['created_at'],
                    confidence=m['rag_confidence']
                )
                for m in messages
            ]

            # 콜백 버튼 표시 여부
            user_msg_count = sum(1 for m in messages if m['role'] == 'user')
            show_callback = user_msg_count >= settings.CALLBACK_TRIGGER_COUNT

            return ChatHistoryResponse(
                session_id=session_id,
                phone=session['phone'],
                message_count=session['message_count'],
                messages=chat_messages,
                status=session['status'],
                show_callback_button=show_callback,
                created_at=session['created_at']
            )


@router.post("/callback", response_model=CallbackResponse)
async def request_callback(request: CallbackRequest):
    """
    상담원 콜백 요청

    - 콜백 요청 저장
    - 외부 서버로 대화 내역 전송
    - 세션 상태 업데이트
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 1. 세션 조회
            await cur.execute("""
                SELECT cs.id, cs.session_id, cs.phone, cs.message_count,
                       cs.status, cs.created_at, ct.call_unique_id, ct.token
                FROM chat_sessions cs
                JOIN chat_tokens ct ON cs.token_id = ct.id
                WHERE cs.session_id = %s
            """, (request.session_id,))
            session = await cur.fetchone()

            if not session:
                raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

            if session['status'] in ('callback_requested', 'callback_sent'):
                return CallbackResponse(
                    success=False,
                    message="이미 콜백 요청이 접수되었습니다.",
                    phone=session['phone']
                )

            # 2. 콜백 요청 생성
            await cur.execute("""
                INSERT INTO chat_callbacks
                (chat_session_id, phone, status)
                VALUES (%s, %s, 'pending')
            """, (session['id'], session['phone']))
            callback_id = cur.lastrowid

            # 3. 세션 상태 업데이트
            await cur.execute("""
                UPDATE chat_sessions
                SET status = 'callback_requested', updated_at = NOW()
                WHERE id = %s
            """, (session['id'],))

            # 4. 대화 내역 조회
            await cur.execute("""
                SELECT role, content, created_at, rag_confidence
                FROM chat_messages
                WHERE chat_session_id = %s
                ORDER BY created_at ASC
            """, (session['id'],))
            messages = await cur.fetchall()

            # 5. 외부 서버로 전송 (헬퍼 함수 사용)
            sent = await send_session_to_external(
                session=session,
                messages=messages,
                callback_requested=True,
                end_reason="callback_requested"
            )

            if sent:
                await cur.execute("""
                    UPDATE chat_callbacks
                    SET status = 'sent', sent_at = NOW()
                    WHERE id = %s
                """, (callback_id,))
                await cur.execute("""
                    UPDATE chat_sessions
                    SET status = 'callback_sent'
                    WHERE id = %s
                """, (session['id'],))

            logger.info(f"Callback requested: session={request.session_id}, callback_id={callback_id}")

            return CallbackResponse(
                success=True,
                callback_id=callback_id,
                message="상담원 연결 요청이 접수되었습니다. 곧 연락드리겠습니다.",
                phone=session['phone']
            )


@router.get("/status/{session_id}")
async def get_session_status(session_id: str):
    """세션 상태 조회"""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT session_id, phone, message_count, status, created_at, updated_at
                FROM chat_sessions
                WHERE session_id = %s
            """, (session_id,))
            session = await cur.fetchone()

            if not session:
                raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

            return {
                "session_id": session['session_id'],
                "phone": session['phone'],
                "message_count": session['message_count'],
                "status": session['status'],
                "created_at": session['created_at'],
                "updated_at": session['updated_at']
            }


@router.post("/end", response_model=EndSessionResponse)
async def end_session(request: EndSessionRequest):
    """
    채팅 세션 종료

    - 세션 상태를 'ended'로 변경
    - 대화 내역을 외부 서버로 전송
    - callback_requested: false로 전송
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 1. 세션 조회
            await cur.execute("""
                SELECT cs.id, cs.session_id, cs.phone, cs.status, cs.created_at,
                       ct.call_unique_id, ct.token
                FROM chat_sessions cs
                JOIN chat_tokens ct ON cs.token_id = ct.id
                WHERE cs.session_id = %s
            """, (request.session_id,))
            session = await cur.fetchone()

            if not session:
                return EndSessionResponse(
                    success=False,
                    message="세션을 찾을 수 없습니다."
                )

            # 이미 종료된 세션인지 확인
            if session['status'] in ('ended', 'callback_sent'):
                return EndSessionResponse(
                    success=True,
                    message="이미 종료된 세션입니다."
                )

            # 2. 대화 내역 조회
            await cur.execute("""
                SELECT role, content, created_at, rag_confidence
                FROM chat_messages
                WHERE chat_session_id = %s
                ORDER BY created_at ASC
            """, (session['id'],))
            messages = await cur.fetchall()

            # 3. 외부 서버로 전송
            callback_requested = session['status'] == 'callback_requested'
            sent = await send_session_to_external(
                session=session,
                messages=messages,
                callback_requested=callback_requested,
                end_reason=request.reason
            )

            # 4. 세션 상태 업데이트
            await cur.execute("""
                UPDATE chat_sessions
                SET status = 'ended', updated_at = NOW()
                WHERE id = %s
            """, (session['id'],))

            logger.info(f"Session ended: {request.session_id}, reason={request.reason}, sent={sent}")

            return EndSessionResponse(
                success=True,
                message="채팅이 종료되었습니다. 이용해 주셔서 감사합니다."
            )


# ===========================================
# Session Timeout Background Task
# ===========================================

_timeout_task = None

async def check_timed_out_sessions():
    """
    타임아웃된 세션 확인 및 처리 (백그라운드 태스크)
    - SESSION_TIMEOUT_MINUTES 이상 활동 없는 세션 종료
    - 외부 서버로 대화 내역 전송
    """
    timeout_minutes = getattr(settings, 'SESSION_TIMEOUT_MINUTES', 30)

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # 타임아웃된 active 세션 조회
                await cur.execute("""
                    SELECT cs.id, cs.session_id, cs.phone, cs.status, cs.created_at,
                           ct.call_unique_id, ct.token
                    FROM chat_sessions cs
                    JOIN chat_tokens ct ON cs.token_id = ct.id
                    WHERE cs.status IN ('active', 'callback_requested')
                    AND cs.updated_at < DATE_SUB(NOW(), INTERVAL %s MINUTE)
                """, (timeout_minutes,))
                timed_out_sessions = await cur.fetchall()

                if timed_out_sessions:
                    logger.info(f"⏱️ Found {len(timed_out_sessions)} timed-out sessions")

                for session in timed_out_sessions:
                    try:
                        # 대화 내역 조회
                        await cur.execute("""
                            SELECT role, content, created_at, rag_confidence
                            FROM chat_messages
                            WHERE chat_session_id = %s
                            ORDER BY created_at ASC
                        """, (session['id'],))
                        messages = await cur.fetchall()

                        # 대화 내역이 없는 경우 건너뛰기
                        if not messages:
                            await cur.execute("""
                                UPDATE chat_sessions
                                SET status = 'ended', updated_at = NOW()
                                WHERE id = %s
                            """, (session['id'],))
                            logger.info(f"⏱️ Empty session ended: {session['session_id']}")
                            continue

                        # 외부 서버로 전송
                        callback_requested = session['status'] == 'callback_requested'
                        sent = await send_session_to_external(
                            session=session,
                            messages=messages,
                            callback_requested=callback_requested,
                            end_reason="timeout"
                        )

                        # 세션 상태 업데이트
                        await cur.execute("""
                            UPDATE chat_sessions
                            SET status = 'ended', updated_at = NOW()
                            WHERE id = %s
                        """, (session['id'],))

                        logger.info(f"⏱️ Session timed out: {session['session_id']}, sent={sent}")

                    except Exception as e:
                        logger.error(f"Error processing timed-out session {session['session_id']}: {e}")

    except Exception as e:
        logger.error(f"Session timeout check failed: {e}")


async def start_timeout_checker():
    """백그라운드 타임아웃 체커 시작"""
    global _timeout_task

    async def run_checker():
        check_interval = 60  # 1분마다 체크
        while True:
            try:
                await check_timed_out_sessions()
            except Exception as e:
                logger.error(f"Timeout checker error: {e}")
            await asyncio.sleep(check_interval)

    _timeout_task = asyncio.create_task(run_checker())
    logger.info(f"⏱️ Session timeout checker started (interval: 60s, timeout: {settings.SESSION_TIMEOUT_MINUTES}min)")


async def stop_timeout_checker():
    """백그라운드 타임아웃 체커 중지"""
    global _timeout_task
    if _timeout_task:
        _timeout_task.cancel()
        try:
            await _timeout_task
        except asyncio.CancelledError:
            pass
        _timeout_task = None
        logger.info("⏱️ Session timeout checker stopped")


# ===========================================
# Feedback Endpoint (고객 채팅용)
# ===========================================

class ChatFeedbackRequest(BaseModel):
    """고객 채팅 피드백 요청"""
    session_id: str
    message_id: Optional[int] = None  # 특정 메시지에 대한 피드백
    is_helpful: bool  # 도움됨/안됨
    comment: Optional[str] = None


class ChatFeedbackResponse(BaseModel):
    """고객 채팅 피드백 응답"""
    success: bool
    message: str


@router.post("/feedback", response_model=ChatFeedbackResponse)
async def submit_chat_feedback(request: ChatFeedbackRequest):
    """
    고객 채팅 피드백 제출

    - 답변이 도움이 되었는지 피드백 저장
    - 기존 session_context 테이블의 피드백 저장 방식 사용
    - 학습 데이터로 활용
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 1. 세션 조회 (rag_session_id 포함)
            await cur.execute("""
                SELECT id, session_id, rag_session_id FROM chat_sessions
                WHERE session_id = %s
            """, (request.session_id,))
            session = await cur.fetchone()

            if not session:
                return ChatFeedbackResponse(
                    success=False,
                    message="세션을 찾을 수 없습니다."
                )

            # 2. 기존 피드백 저장 방식 사용 (session_context 테이블)
            rag_session_id = session.get('rag_session_id')

            if rag_session_id:
                try:
                    from repositories.session_context_repository import SessionContextRepository
                    repo = SessionContextRepository()

                    # is_helpful → satisfaction 매핑 (도움됨=5, 안됨=1)
                    satisfaction = 5 if request.is_helpful else 1
                    is_relevant = request.is_helpful

                    saved = repo.update_satisfaction(
                        session_id=rag_session_id,
                        satisfaction=satisfaction,
                        is_relevant=is_relevant,
                        comment=request.comment
                    )

                    if saved:
                        logger.info(
                            f"💬 Chat feedback saved: chat_session={request.session_id}, "
                            f"rag_session={rag_session_id}, helpful={request.is_helpful}"
                        )
                        return ChatFeedbackResponse(
                            success=True,
                            message="피드백이 저장되었습니다. 감사합니다!"
                        )
                    else:
                        logger.warning(f"⚠️ Feedback not saved (RAG session not found): {rag_session_id}")

                except Exception as e:
                    logger.error(f"Feedback save error: {e}")

            # RAG 세션이 없거나 저장 실패 시에도 로그 남김
            logger.info(f"💬 Chat feedback (no RAG session): session={request.session_id}, helpful={request.is_helpful}")

            return ChatFeedbackResponse(
                success=True,
                message="피드백이 접수되었습니다. 감사합니다!"
            )
