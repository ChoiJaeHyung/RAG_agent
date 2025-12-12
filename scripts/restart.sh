#!/bin/bash
#
# R-Agent 서비스 재시작 스크립트
# Usage: ./restart.sh [all|api|ui]
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 색상 정의
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔄 R-Agent 서비스 재시작${NC}"
echo "================================"

# 중단
"$SCRIPT_DIR/stop.sh" "${1:-all}"

# 잠시 대기
sleep 2

# 시작
"$SCRIPT_DIR/start.sh" "${1:-all}"
