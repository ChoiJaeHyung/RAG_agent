/**
 * 클콜 연동 테스트 (SMS 발송 없이 전화번호만 확인)
 * sample_contect 폴더의 socket_frame.js, main.js 참고
 */

require('dotenv').config({ path: '../.env' });
const io = require('socket.io-client');
const crypto = require('crypto');

// SHA512 해시 함수 (sha512.js의 hex_sha512 대체)
function sha512(str) {
    return crypto.createHash('sha512').update(str).digest('hex');
}

const config = {
    // 포트 8087
    url: `https://${process.env.CALLCENTER_URL}:8087/`,
    companyId: process.env.CALLCENTER_COMPANY_ID,
    userId: process.env.CALLCENTER_USER_ID,
    password: sha512(process.env.CALLCENTER_PASSWORD),  // SHA512 해시
    rawPassword: process.env.CALLCENTER_PASSWORD,
    exten: process.env.CALLCENTER_EXTEN,
    serverIp: '222.231.0.74',  // 교환기 IP (수정됨)
    usertype: 'M',             // 상담원 유형 (기본값)
    option: '0'                // 로그인 후 상태 (0=대기)
};

// CALLEVENT 파싱 (socket_frame.js parseMessage 참조)
function parseMessage(msg) {
    const msgs = msg.split('|');
    if (!msgs || msgs.length < 2) return { event: null };

    const result = { event: msgs[0] };

    for (let i = 1; i < msgs.length; i++) {
        const keyval = msgs[i].split(':');
        if (keyval.length >= 2) {
            // 값에 ':'이 포함된 경우 처리
            let value = keyval.slice(1).join(':');
            result[keyval[0]] = value;
        }
    }
    return result;
}

// 전화번호 정규화
function normalizePhone(phone) {
    if (!phone) return null;
    const digits = phone.replace(/\D/g, '');
    if (digits.length >= 10 && digits.length <= 11) {
        return digits;
    }
    return null;
}

console.log('========================================');
console.log('  클콜 연동 테스트 (SMS 발송 안함)');
console.log('========================================');
console.log(`서버: ${config.url}`);
console.log(`회사: ${config.companyId}`);
console.log(`사용자: ${config.userId}`);
console.log(`내선: ${config.exten}`);
console.log(`교환기IP: ${config.serverIp}`);
console.log('========================================\n');

// 로그인 데이터 준비
const loginData = {
    company_id: config.companyId,
    userid: config.userId,
    exten: config.exten,
    passwd: config.password,
    serverip: config.serverIp,
    usertype: config.usertype,
    option: config.option
};

// Socket.io 연결 - WebSocket만 사용
const socket = io.connect(config.url, {
    'secure': true,
    'reconnect': true,
    'resource': 'socket.io',
    'transports': ['websocket']  // WebSocket만 사용
});

// ★★★ 원본처럼 연결 직후 바로 emit (이벤트 핸들러 등록 전!) ★★★
console.log('🔐 로그인 시도... (climsg_login)');
console.log('   데이터:', JSON.stringify(loginData, null, 2));
socket.emit('climsg_login', loginData);

// 그 다음에 이벤트 핸들러 등록 (원본 순서와 동일)
socket.on('connect', () => {
    console.log('✅ 클콜 서버 연결 성공');
});

// 서버 메시지 수신 (socket_frame.js 라인 50-52)
socket.on('svcmsg', (data) => {
    console.log('\n📥 svcmsg 수신:', data);

    const parsed = parseMessage(data);
    console.log('파싱 결과:', JSON.stringify(parsed, null, 2));

    // LOGIN 이벤트 처리
    if (parsed.event === 'LOGIN') {
        if (parsed.KIND === 'LOGIN_OK') {
            console.log('\n✅ 로그인 성공!');
            console.log('   내선:', parsed.DATA1);
            console.log('   이름:', parsed.DATA2);
            console.log('   상태:', parsed.DATA3);
            console.log('   전화기상태:', parsed.DATA4);

            // LOGIN_ACK 전송 필수! (main.js 라인 214)
            console.log('\n📤 LOGIN_ACK 전송...');
            socket.emit('climsg_command', 'CMD|LOGIN_ACK');

            // 3초 후 전화 걸기 테스트
            setTimeout(() => {
                const phoneNumber = '01029270423';
                console.log(`\n📞 전화 걸기 요청: ${phoneNumber}`);
                // 형식: CLICKDIAL|RID(발신번호),수신번호,outbound
                // 원본 main.js는 "oubbound" (오타)로 되어 있음
                socket.emit('climsg_command', `CMD|CLICKDIAL|,${phoneNumber},oubbound`);
            }, 3000);

            console.log('\n📞 전화 대기 중... (Ctrl+C로 종료)\n');
        } else {
            console.log('\n❌ 로그인 실패:', parsed.KIND, parsed.DATA1);
        }
    }
    // CALLEVENT 처리
    else if (parsed.event === 'CALLEVENT') {
        console.log('\n========================================');
        console.log('📞 CALLEVENT!');
        console.log('========================================');

        if (parsed.KIND === 'IR') {
            const phone = normalizePhone(parsed.DATA1);
            console.log('🔔 수신 전화 (KIND: IR)');
            console.log('   📱 발신번호 (DATA1):', parsed.DATA1);
            console.log('   📱 정규화:', phone);
            console.log('   🆔 CALL_UNIQUEID (DATA8):', parsed.DATA8);
            console.log('\n   ⚠️  테스트 모드 - SMS 발송 안함');
        } else {
            console.log('   ℹ️  KIND:', parsed.KIND);
            console.log('   DATA1:', parsed.DATA1);
            console.log('   DATA2:', parsed.DATA2);
        }
        console.log('========================================\n');
    }
    // HANGUPEVENT 처리
    else if (parsed.event === 'HANGUPEVENT') {
        console.log('\n📴 통화 종료 (HANGUPEVENT)');
        // HANGUP_ACK 전송
        if (parsed.DATA5) {
            socket.emit('climsg_command', `CMD|HANGUP_ACK|${parsed.DATA5},${parsed.DATA8 || '0'}`);
        }
    }
    // MEMBERSTATUS 처리
    else if (parsed.event === 'MEMBERSTATUS') {
        console.log('👤 상태 변경:', parsed.KIND);
    }
});

// Ping-Pong (socket_frame.js 라인 53-55)
socket.on('svcmsg_ping', () => {
    console.log('🏓 ping 수신 → pong 전송');
    socket.emit('climsg_pong');
});

// 연결 끊김
socket.on('disconnect', (reason) => {
    console.warn('\n⚠️ 연결 끊김:', reason);
});

// 에러
socket.on('connect_error', (error) => {
    console.error('❌ 연결 에러:', error.message);
});

socket.on('error', (error) => {
    console.error('❌ 소켓 에러:', error);
});

// 종료 처리
process.on('SIGINT', () => {
    console.log('\n\n🛑 종료...');
    socket.emit('climsg_command', 'Bye.');
    setTimeout(() => {
        socket.disconnect();
        process.exit(0);
    }, 500);
});
