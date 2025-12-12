#!/bin/bash
#
# R-Agent 서비스 상태 확인 스크립트
# Usage: ./status.sh
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# PID 파일 경로
API_PID_FILE="$PROJECT_DIR/.api.pid"
UI_PID_FILE="$PROJECT_DIR/.ui.pid"

# 포트 설정 (nginx: 443→8000 prod, 8443→8001 dev 사용중)
API_PORT=${API_PORT:-8002}
UI_PORT=${UI_PORT:-8501}

check_service() {
    local port=$1
    local name=$2
    local pid_file=$3
    local url=$4

    echo -e "\n${BLUE}[$name]${NC}"

    # 포트 확인
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        local pid=$(lsof -ti :$port 2>/dev/null | head -1)
        echo -e "  상태:    ${GREEN}● 실행 중${NC}"
        echo -e "  PID:     $pid"
        echo -e "  포트:    $port"
        echo -e "  URL:     $url"

        # Health check (API만)
        if [ "$name" = "API 서버" ]; then
            local health=$(curl -s --max-time 3 "http://localhost:$port/health" 2>/dev/null)
            if [ -n "$health" ]; then
                local status=$(echo "$health" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
                if [ "$status" = "healthy" ]; then
                    echo -e "  Health:  ${GREEN}healthy${NC}"
                else
                    echo -e "  Health:  ${YELLOW}$status${NC}"
                fi
            fi
        fi

        return 0
    else
        echo -e "  상태:    ${RED}○ 중지됨${NC}"
        return 1
    fi
}

show_logs() {
    local log_dir="$PROJECT_DIR/logs"

    echo -e "\n${BLUE}[최근 로그]${NC}"

    if [ -f "$log_dir/api.log" ]; then
        echo -e "\n  📄 API 로그 (마지막 5줄):"
        tail -5 "$log_dir/api.log" 2>/dev/null | sed 's/^/     /'
    fi

    if [ -f "$log_dir/ui.log" ]; then
        echo -e "\n  📄 UI 로그 (마지막 5줄):"
        tail -5 "$log_dir/ui.log" 2>/dev/null | sed 's/^/     /'
    fi
}

# 헤더
echo ""
echo "╔════════════════════════════════════════╗"
echo "║       R-Agent 서비스 상태              ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "시간: $(date '+%Y-%m-%d %H:%M:%S')"

# 서비스 상태 확인
check_service $API_PORT "API 서버" "$API_PID_FILE" "http://0.0.0.0:$API_PORT"
API_STATUS=$?

check_service $UI_PORT "Chat UI" "$UI_PID_FILE" "http://0.0.0.0:$UI_PORT"
UI_STATUS=$?

# 요약
echo ""
echo "════════════════════════════════════════"
echo -n "전체 상태: "

if [ $API_STATUS -eq 0 ] && [ $UI_STATUS -eq 0 ]; then
    echo -e "${GREEN}모든 서비스 정상${NC}"
elif [ $API_STATUS -eq 0 ] || [ $UI_STATUS -eq 0 ]; then
    echo -e "${YELLOW}일부 서비스 중단${NC}"
else
    echo -e "${RED}모든 서비스 중단${NC}"
fi

# 로그 옵션
if [ "$1" = "-l" ] || [ "$1" = "--logs" ]; then
    show_logs
fi

echo ""
echo "사용법: $0 [-l|--logs]  # 로그 포함 출력"
