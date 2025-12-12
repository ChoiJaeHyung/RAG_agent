#!/bin/bash

# ================================================================
# R-Agent Learning Database 자동 설치 스크립트
# ================================================================
# 사용법: bash database/install.sh
# ================================================================

set -e  # 오류 발생 시 즉시 종료

echo ""
echo "================================================================"
echo "  R-Agent Learning Database 설치"
echo "================================================================"
echo ""

# 설정
DB_HOST="127.0.0.1"
DB_PORT="9443"
DB_USER="rsup"
DB_PASS="rsup#EDC3900"

# 색상 정의
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1단계: 데이터베이스 생성
echo "================================================================"
echo "  1. 데이터베이스 생성 중..."
echo "================================================================"

if mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASS < database/01_create_database.sql; then
    echo -e "${GREEN}✅ 데이터베이스 생성 성공${NC}"
else
    echo -e "${RED}❌ 데이터베이스 생성 실패${NC}"
    exit 1
fi

echo ""

# 2단계: 테이블 생성
echo "================================================================"
echo "  2. 테이블 생성 중..."
echo "================================================================"

if mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASS < database/02_create_tables.sql; then
    echo -e "${GREEN}✅ 테이블 생성 성공${NC}"
else
    echo -e "${RED}❌ 테이블 생성 실패${NC}"
    exit 1
fi

echo ""

# 3단계: 설치 검증
echo "================================================================"
echo "  3. 설치 검증 중..."
echo "================================================================"

if python database/test_learning_db.py; then
    echo ""
    echo -e "${GREEN}✨ Learning Database 설치 완료!${NC}"
    echo ""
    echo "다음 단계:"
    echo "  1. SearchAgent에 성능 추적 통합"
    echo "  2. 실제 쿼리로 데이터 축적 시작"
    echo "  3. 학습 기능 활성화"
    echo ""
else
    echo ""
    echo -e "${YELLOW}⚠️  검증 실패. 수동으로 확인이 필요합니다.${NC}"
    echo ""
    echo "수동 확인 방법:"
    echo "  mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASS r_agent_db"
    echo "  > SHOW TABLES;"
    echo ""
    exit 1
fi

echo "================================================================"
