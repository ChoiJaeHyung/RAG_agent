/**
 * LG U+ 클콜 LITE Socket.io 클라이언트
 *
 * 흐름:
 * 1. 클콜 서버 연결 → 로그인
 * 2. CALLEVENT 수신 (KIND:IR = 수신 전화)
 * 3. 토큰 생성 → R-Agent DB 저장
 * 4. SMS 발송 → LG U+ SC_TRAN 테이블 INSERT
 */

require('dotenv').config({ path: '../.env' });
const { io } = require('socket.io-client');
const mysql = require('mysql2/promise');
const { v4: uuidv4 } = require('uuid');
const axios = require('axios');

// ===========================================
// 설정
// ===========================================
const config = {
    // 클콜 LITE
    callcenter: {
        url: `https://${process.env.CALLCENTER_URL}`,
        companyId: process.env.CALLCENTER_COMPANY_ID,
        userId: process.env.CALLCENTER_USER_ID,
        password: process.env.CALLCENTER_PASSWORD,
        exten: process.env.CALLCENTER_EXTEN
    },
    // SMS DB (LG U+)
    smsDb: {
        host: process.env.SMS_DB_HOST,
        port: parseInt(process.env.SMS_DB_PORT) || 3306,
        database: process.env.SMS_DB_NAME,
        user: process.env.SMS_DB_USER,
        password: process.env.SMS_DB_PASSWORD
    },
    // R-Agent DB
    agentDb: {
        host: process.env.LEARNING_DB_HOST || '127.0.0.1',
        port: parseInt(process.env.LEARNING_DB_PORT) || 9443,
        database: process.env.LEARNING_DB_NAME || 'r_agent_db',
        user: process.env.LEARNING_DB_USER || 'rsup',
        password: process.env.LEARNING_DB_PASSWORD || 'rsup#EDC3900'
    },
    // 채팅
    chatDomain: process.env.CHAT_DOMAIN || 'https://chat.example.com',
    tokenExpireHours: parseInt(process.env.CHAT_TOKEN_EXPIRE_HOURS) || 24,
    smsCallback: process.env.SMS_CALLBACK_NUMBER || '07070113900'
};

// ===========================================
// DB 연결 풀
// ===========================================
let smsPool = null;
let agentPool = null;

async function initDbPools() {
    try {
        // SMS DB 풀
        smsPool = mysql.createPool({
            ...config.smsDb,
            waitForConnections: true,
            connectionLimit: 5,
            queueLimit: 0
        });
        console.log('✅ SMS DB 연결 풀 생성');

        // R-Agent DB 풀
        agentPool = mysql.createPool({
            ...config.agentDb,
            waitForConnections: true,
            connectionLimit: 5,
            queueLimit: 0
        });
        console.log('✅ R-Agent DB 연결 풀 생성');

    } catch (error) {
        console.error('❌ DB 연결 실패:', error.message);
        process.exit(1);
    }
}

// ===========================================
// 토큰 생성 및 저장
// ===========================================
async function createChatToken(phone, callUniqueId, callEventRaw) {
    const token = uuidv4();
    const expiresAt = new Date(Date.now() + config.tokenExpireHours * 60 * 60 * 1000);

    try {
        const [result] = await agentPool.execute(
            `INSERT INTO chat_tokens (token, phone, call_unique_id, call_event_raw, expires_at)
             VALUES (?, ?, ?, ?, ?)`,
            [token, phone, callUniqueId, callEventRaw, expiresAt]
        );

        console.log(`✅ 토큰 생성: ${token.substring(0, 8)}... (ID: ${result.insertId})`);
        return { token, tokenId: result.insertId };

    } catch (error) {
        console.error('❌ 토큰 생성 실패:', error.message);
        throw error;
    }
}

// ===========================================
// SMS 발송 (SC_TRAN 테이블 INSERT)
// ===========================================
async function sendSms(phone, token, tokenId) {
    const chatUrl = `${config.chatDomain}?token=${token}`;
    const message = `기술문의: ${chatUrl}`;

    // 메시지 길이 체크 (90byte 이내 - SMS 제한)
    if (Buffer.byteLength(message, 'utf8') > 90) {
        console.warn('⚠️ SMS 메시지가 90byte 초과, LMS로 전환될 수 있음');
    }

    try {
        // LG U+ SC_TRAN 테이블 INSERT
        await smsPool.execute(
            `INSERT INTO SC_TRAN (TR_PHONE, TR_CALLBACK, TR_MSG, TR_SENDDATE, TR_SENDSTAT, TR_MSGTYPE)
             VALUES (?, ?, ?, NOW(), '0', '0')`,
            [phone, config.smsCallback, message]
        );

        // R-Agent SMS 로그 기록
        await agentPool.execute(
            `INSERT INTO sms_send_log (token_id, phone, callback_number, message, status, sc_tran_inserted)
             VALUES (?, ?, ?, ?, 'sent', TRUE)`,
            [tokenId, phone, config.smsCallback, message]
        );

        console.log(`📱 SMS 발송: ${phone} → ${chatUrl.substring(0, 40)}...`);
        return true;

    } catch (error) {
        console.error('❌ SMS 발송 실패:', error.message);

        // 에러 로그 기록
        try {
            await agentPool.execute(
                `INSERT INTO sms_send_log (token_id, phone, callback_number, message, status, sc_tran_inserted, sc_tran_error)
                 VALUES (?, ?, ?, ?, 'failed', FALSE, ?)`,
                [tokenId, phone, config.smsCallback, message, error.message]
            );
        } catch (logError) {
            console.error('❌ SMS 로그 기록 실패:', logError.message);
        }

        throw error;
    }
}

// ===========================================
// CALLEVENT 파싱
// ===========================================
function parseCallEvent(eventData) {
    // 형식: CALLEVENT|KIND:IR|COMP:rsupport|PEER:...|DATA1:01012345678|...|DATA8:1427344822.1189678
    const parts = eventData.split('|');
    const result = {};

    for (const part of parts) {
        const [key, value] = part.split(':');
        if (key && value) {
            result[key] = value;
        }
    }

    return result;
}

// ===========================================
// 전화번호 정규화
// ===========================================
function normalizePhone(phone) {
    if (!phone) return null;
    // 숫자만 추출
    const digits = phone.replace(/\D/g, '');
    // 010으로 시작하는 11자리 또는 02 등으로 시작하는 번호
    if (digits.length >= 10 && digits.length <= 11) {
        return digits;
    }
    return null;
}

// ===========================================
// 수신 전화 처리
// ===========================================
async function handleInboundCall(eventData) {
    const parsed = parseCallEvent(eventData);

    // KIND:IR (Inbound Ringing) 확인
    if (parsed.KIND !== 'IR') {
        return;
    }

    const phone = normalizePhone(parsed.DATA1);
    const callUniqueId = parsed.DATA8;

    if (!phone) {
        console.warn('⚠️ 유효하지 않은 전화번호:', parsed.DATA1);
        return;
    }

    console.log(`\n📞 수신 전화: ${phone} (CALL_ID: ${callUniqueId})`);

    try {
        // 1. 토큰 생성
        const { token, tokenId } = await createChatToken(phone, callUniqueId, eventData);

        // 2. SMS 발송
        await sendSms(phone, token, tokenId);

        console.log(`✅ 처리 완료: ${phone}\n`);

    } catch (error) {
        console.error(`❌ 처리 실패: ${phone}`, error.message);
    }
}

// ===========================================
// Socket.io 클라이언트
// ===========================================
function connectCallCenter() {
    console.log(`\n🔌 클콜 서버 연결 중: ${config.callcenter.url}`);

    const socket = io(config.callcenter.url, {
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000
    });

    // 연결 성공
    socket.on('connect', () => {
        console.log('✅ 클콜 서버 연결 성공');

        // 로그인
        const loginData = {
            company_id: config.callcenter.companyId,
            userid: config.callcenter.userId,
            exten: config.callcenter.exten,
            passwd: config.callcenter.password
        };

        console.log(`🔐 로그인 시도: ${config.callcenter.userId}@${config.callcenter.companyId}`);
        socket.emit('login', loginData);
    });

    // 로그인 응답
    socket.on('login_result', (data) => {
        if (data.success || data.result === 'success') {
            console.log('✅ 로그인 성공');
            console.log('📡 CALLEVENT 대기 중...\n');
        } else {
            console.error('❌ 로그인 실패:', data);
        }
    });

    // 전화 이벤트 수신
    socket.on('CALLEVENT', (data) => {
        console.log('📥 CALLEVENT:', data);
        handleInboundCall(data);
    });

    // 기타 이벤트 (디버깅용)
    socket.on('message', (data) => {
        console.log('📨 메시지:', data);
    });

    // 연결 끊김
    socket.on('disconnect', (reason) => {
        console.warn('⚠️ 연결 끊김:', reason);
    });

    // 재연결
    socket.on('reconnect', (attemptNumber) => {
        console.log(`🔄 재연결 성공 (시도 ${attemptNumber}회)`);
    });

    // 에러
    socket.on('connect_error', (error) => {
        console.error('❌ 연결 에러:', error.message);
    });

    socket.on('error', (error) => {
        console.error('❌ 소켓 에러:', error);
    });

    return socket;
}

// ===========================================
// 메인
// ===========================================
async function main() {
    console.log('========================================');
    console.log('  LG U+ 클콜 LITE 클라이언트');
    console.log('========================================');
    console.log(`회사: ${config.callcenter.companyId}`);
    console.log(`사용자: ${config.callcenter.userId}`);
    console.log(`내선: ${config.callcenter.exten}`);
    console.log(`채팅 도메인: ${config.chatDomain}`);
    console.log('========================================\n');

    // DB 연결
    await initDbPools();

    // 클콜 서버 연결
    const socket = connectCallCenter();

    // 종료 처리
    process.on('SIGINT', async () => {
        console.log('\n\n🛑 종료 중...');
        socket.disconnect();
        if (smsPool) await smsPool.end();
        if (agentPool) await agentPool.end();
        console.log('👋 종료 완료');
        process.exit(0);
    });
}

main().catch(console.error);
