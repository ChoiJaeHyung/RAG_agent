/**
 * DB 연결 테스트 스크립트
 */

require('dotenv').config({ path: '../.env' });
const mysql = require('mysql2/promise');

async function testConnections() {
    console.log('========================================');
    console.log('  DB 연결 테스트');
    console.log('========================================\n');

    // 환경변수 확인
    console.log('📋 환경변수 확인:');
    console.log(`   LEARNING_DB_HOST: ${process.env.LEARNING_DB_HOST}`);
    console.log(`   LEARNING_DB_PORT: ${process.env.LEARNING_DB_PORT}`);
    console.log(`   LEARNING_DB_NAME: ${process.env.LEARNING_DB_NAME}`);
    console.log(`   LEARNING_DB_USER: ${process.env.LEARNING_DB_USER}`);
    console.log(`   LEARNING_DB_PASSWORD: ${process.env.LEARNING_DB_PASSWORD ? '***설정됨***' : '미설정'}`);
    console.log();

    // R-Agent DB 테스트
    console.log('1️⃣ R-Agent DB 테스트...');
    try {
        const agentConn = await mysql.createConnection({
            host: process.env.LEARNING_DB_HOST || '127.0.0.1',
            port: parseInt(process.env.LEARNING_DB_PORT || '9443'),
            database: process.env.LEARNING_DB_NAME || 'r_agent_db',
            user: process.env.LEARNING_DB_USER || 'rsup',
            password: process.env.LEARNING_DB_PASSWORD || ''
        });

        const [tables] = await agentConn.query("SHOW TABLES LIKE 'chat%'");
        console.log('   ✅ R-Agent DB 연결 성공');
        console.log(`   📋 Chat 테이블 수: ${tables.length}`);
        tables.forEach(t => console.log(`      - ${Object.values(t)[0]}`));

        await agentConn.end();
    } catch (error) {
        console.log('   ❌ R-Agent DB 연결 실패:', error.message);
    }

    // SMS DB 테스트
    console.log('\n2️⃣ SMS DB (LG U+) 테스트...');
    try {
        const smsConn = await mysql.createConnection({
            host: process.env.SMS_DB_HOST,
            port: parseInt(process.env.SMS_DB_PORT) || 3306,
            database: process.env.SMS_DB_NAME,
            user: process.env.SMS_DB_USER,
            password: process.env.SMS_DB_PASSWORD
        });

        const [tables] = await smsConn.query("SHOW TABLES LIKE 'SC%'");
        console.log('   ✅ SMS DB 연결 성공');
        console.log(`   📋 SC 테이블 수: ${tables.length}`);
        tables.forEach(t => console.log(`      - ${Object.values(t)[0]}`));

        await smsConn.end();
    } catch (error) {
        console.log('   ❌ SMS DB 연결 실패:', error.message);
        console.log('   ⚠️  SMS 발송은 네트워크 접근이 필요합니다.');
    }

    console.log('\n========================================');
    console.log('  테스트 완료');
    console.log('========================================');
}

testConnections().catch(console.error);
