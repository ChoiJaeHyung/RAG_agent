# AI 고객상담 시스템 구축 가이드

## 프로젝트 개요

LG U+ 클콜 LITE API를 활용하여 전화 수신 시 웹 채팅으로 유도하고, AI(RAG)가 자동 응대 후 필요시 상담원 콜백을 요청하는 시스템

---

## 시스템 흐름

```
[1] 고객 전화 수신
    └─→ LG U+ 클콜 LITE (Socket.io)
    └─→ CALLEVENT 이벤트 수신
    └─→ DATA1에서 고객 전화번호 추출

[2] SMS 발송
    └─→ 일회용 토큰 생성 (UUID)
    └─→ DB 저장 (token, phone, created_at, expires_at)
    └─→ SMS DB INSERT (SC_TRAN)
        "기술문의: https://chat.도메인.com?token=abc123xyz"

[3] 웹 채팅 (고객)
    └─→ 토큰 검증 (유효성, 만료여부)
    └─→ 채팅 UI 표시
    └─→ 고객 메시지 입력
    └─→ RAG API 호출 (웹훅)
    └─→ AI 응답 표시
    └─→ 5회 응답 후 "상담원 통화 요청" 버튼 표시

[4] 콜백 요청
    └─→ 버튼 클릭
    └─→ 콜백 DB 저장
    └─→ 외부 서버로 대화내역 전송
        POST {EXTERNAL_SERVER}/call-history/callbot
    └─→ 상담원이 웹페이지에서 목록 확인 후 콜백
```

---

## 환경변수 (.env)

```env
# === LG U+ 클콜 LITE ===
CALLCENTER_URL=cloudlite.uplus.co.kr
CALLCENTER_COMPANY_ID=rsupport
CALLCENTER_USER_ID=user4491
CALLCENTER_PASSWORD=user!234
CALLCENTER_EXTEN=4491

# === SMS DB (LG U+) ===
SMS_DB_HOST=172.25.237.126
SMS_DB_PORT=3306
SMS_DB_NAME=lguplus
SMS_DB_USER=lguplus
SMS_DB_PASSWORD=Rsup4430#
SMS_CALLBACK_NUMBER=07070113900

# === RAG API ===
RAG_API_URL=http://localhost:8002
RAG_WEBHOOK_PATH=/webhook/rag

# === 웹 채팅 ===
CHAT_DOMAIN=https://chat.example.com
CHAT_TOKEN_EXPIRE_HOURS=24

# === 서버 ===
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
DATABASE_URL=sqlite:///./app.db

# === 콜백 설정 ===
CALLBACK_TRIGGER_COUNT=5
EXTERNAL_CALLBACK_URL=http://다른서버/call-history/callbot
```

---

## 기술 스택

| 구성요소 | 기술 |
|---------|------|
| 클콜 연동 | Node.js + Socket.io Client |
| 백엔드 API | FastAPI (Python) 또는 Express (Node.js) |
| 웹 채팅 프론트 | React 또는 Vanilla JS |
| DB | PostgreSQL 또는 SQLite |
| 토큰 | UUID v4 |
| SMS | MySQL DB INSERT (LG U+ SC_TRAN 테이블) |
| RAG | 기존 RAG API 연동 (웹훅 방식) |

---

## DB 스키마 (기존 DB 스키마 확인해서 과연 효율적일지 분석해줘)

```sql
-- ============================================
-- 채팅 토큰 (SMS 링크용)
-- ============================================
CREATE TABLE chat_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token VARCHAR(36) UNIQUE NOT NULL,
    phone VARCHAR(20) NOT NULL,
    caller_id VARCHAR(50),                  -- 클콜 CALLEVENT DATA8 (CALL_UNIQUEID)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    used BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_chat_tokens_token ON chat_tokens(token);
CREATE INDEX idx_chat_tokens_phone ON chat_tokens(phone);

-- ============================================
-- 채팅 세션
-- ============================================
CREATE TABLE chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id VARCHAR(36) UNIQUE NOT NULL,
    token_id INTEGER NOT NULL,
    phone VARCHAR(20) NOT NULL,
    rag_session_id VARCHAR(100),            -- RAG API 반환 session_id
    message_count INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',    -- active, callback_requested, closed
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME,
    
    FOREIGN KEY (token_id) REFERENCES chat_tokens(id)
);

CREATE INDEX idx_chat_sessions_session_id ON chat_sessions(session_id);
CREATE INDEX idx_chat_sessions_status ON chat_sessions(status);

-- ============================================
-- 채팅 메시지
-- ============================================
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role VARCHAR(10) NOT NULL,              -- 'user' 또는 'assistant'
    content TEXT NOT NULL,
    rag_task_id VARCHAR(100),               -- RAG task_id (assistant일 때)
    rag_confidence FLOAT,                   -- RAG 신뢰도 (assistant일 때)
    rag_sources TEXT,                       -- RAG 참조 문서 JSON (assistant일 때)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);

CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);

-- ============================================
-- 콜백 요청
-- ============================================
CREATE TABLE callbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    phone VARCHAR(20) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',   -- pending, sent, completed
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    sent_at DATETIME,                       -- 외부 서버 전송 완료 시간
    completed_at DATETIME,                  -- 상담원 처리 완료 시간
    external_id VARCHAR(100),               -- 외부 서버 반환 ID
    
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);

CREATE INDEX idx_callbacks_status ON callbacks(status);
CREATE INDEX idx_callbacks_phone ON callbacks(phone);
```

---

## 구현 태스크

### Phase 1: 클콜 연동 + SMS 발송

#### Task 1.1: 클콜 Socket.io 클라이언트
```
- [ ] LG U+ 클콜 서버 연결
- [ ] 로그인 처리 (company_id, userid, exten, passwd)
- [ ] CALLEVENT 이벤트 리스닝
- [ ] KIND:IR (Inbound Ringing) 필터링
- [ ] DATA1 (발신번호), DATA8 (CALL_UNIQUEID) 추출
```

#### Task 1.2: 토큰 생성 및 저장
```
- [ ] UUID 토큰 생성
- [ ] chat_tokens 테이블 INSERT
- [ ] 토큰 검증 함수 (유효성, 만료, 사용여부)
```

#### Task 1.3: SMS 발송
```
- [ ] MySQL 연결 (lguplus DB)
- [ ] SC_TRAN 테이블 INSERT
- [ ] 메시지: "기술문의: {CHAT_DOMAIN}?token={token}" (90byte 이내)
```

---

### Phase 2: 웹 채팅 백엔드(기존 R-agent api 활용)

#### Task 2.1: API 엔드포인트
```

#### Task 2.2: 외부 서버 전송 (콜백 요청 시)
```
외부서버에 준비해야할 DB 스키마 정리 해줘.
POST {EXTERNAL_CALLBACK_URL}

요청 body:
{
  "callback_id": 123,
  "phone": "01012345678",
  "requested_at": "2025-01-15T10:30:00Z",
  "session_info": {
    "session_id": "uuid-xxx",
    "started_at": "2025-01-15T10:00:00Z",
    "message_count": 5
  },
  "conversation": [
    {
      "role": "user",
      "content": "RemoteCall 설치가 안돼요",
      "timestamp": "2025-01-15T10:00:05Z"
    },
    {
      "role": "assistant",
      "content": "어떤 OS를 사용하고 계신가요?",
      "timestamp": "2025-01-15T10:00:08Z",
      "confidence": 0.85
    }
  ],
  "metadata": {
    "caller_id": "1427344822.1189678",
    "token": "abc-123-xyz"
  }
}

- 전송 성공 시: callbacks.status = 'sent', sent_at 기록
- 전송 실패 시: 재시도 또는 에러 로깅
```

---

### Phase 3: 웹 채팅 프론트엔드

#### Task 3.1: 채팅 UI (기존 Chat_ui_prod.py 개선)
```
- [ ] URL에서 토큰 파라미터 읽기
- [ ] GET /chat/verify 호출
- [ ] 유효하지 않으면 에러 페이지
- [ ] 채팅 인터페이스
      - 메시지 입력창
      - 메시지 목록 (스크롤)
      - RAG 응답 대기 표시 (로딩)
- [ ] message_count >= 5 이면 "상담원 통화 요청" 버튼 표시
- [ ] 콜백 요청 완료 화면
```

#### Task 3.2: 보안
```
- [ ] 토큰 없이 접근 시 차단
- [ ] 만료된 토큰 차단
- [ ] 이미 콜백 요청된 세션 처리
- [ ] Rate limiting (도배 방지)
```

---

### Phase 4: 실시간 통신

#### Task 4.1: RAG 응답 전달 방식 선택
```
옵션 A: WebSocket
- 클라이언트 접속 시 WebSocket 연결
- /webhook/rag 수신 시 해당 세션에 push

옵션 B: Server-Sent Events (SSE)
- GET /chat/stream?session_id=xxx
- /webhook/rag 수신 시 SSE로 전달

옵션 C: Polling
- 클라이언트가 주기적으로 GET /chat/history 호출
- 가장 간단하지만 비효율적
```

---

## API 상세 스펙

### LG U+ 클콜 LITE
```
- URL: cloudlite.uplus.co.kr
- company_id: rsupport
- userid: user4491
- passwd: user!234
- exten: 4491

CALLEVENT 예시:
CALLEVENT|KIND:IR|COMP:rsupport|PEER:46908256|DATA1:01012345678|DATA2:4491|DATA3:07070113900|...|DATA8:1427344822.1189678

- KIND:IR = Inbound Ringing (수신 전화)
- DATA1 = 발신번호 (고객 전화번호)
- DATA8 = CALL_UNIQUEID
```

### SMS 발송
```sql
INSERT INTO SC_TRAN (TR_PHONE, TR_CALLBACK, TR_MSG, TR_SENDDATE, TR_SENDSTAT, TR_MSGTYPE)
VALUES ('01012345678', '07070113900', '기술문의: https://chat.xxx.com?token=abc123', NOW(), '0', '0');
```

### agent API (웹훅 방식)


## 개발 순서

```
1. DB 스키마 생성 (init.sql)
2. 클콜 Socket.io 클라이언트 + SMS 발송 테스트
3. 백엔드 토큰 검증 + 세션 생성 API
4. 백엔드 메시지 API + RAG 웹훅 수신
5. 프론트엔드 채팅 UI
6. 실시간 응답 전달 (WebSocket/SSE)
7. 콜백 요청 + 외부 서버 전송
8. 통합 테스트
```
