#!/bin/bash
#
# R-Agent 서비스 중단 스크립트
# Usage: ./stop.sh [all|api|ui]
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# PID 파일 경로
API_PID_FILE="$PROJECT_DIR/.api.pid"
UI_PID_FILE="$PROJECT_DIR/.ui.pid"

# 포트 설정 (nginx: 443→8000 prod, 8443→8001 dev 사용중)
API_PORT=${API_PORT:-8002}
UI_PORT=${UI_PORT:-8501}

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

stop_by_pid_file() {
    local pid_file=$1
    local name=$2

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 $pid 2>/dev/null; then
            kill $pid 2>/dev/null
            sleep 2
            if kill -0 $pid 2>/dev/null; then
                kill -9 $pid 2>/dev/null
            fi
            print_status "$name 중단 완료 (PID: $pid)"
        fi
        rm -f "$pid_file"
    fi
}

stop_by_port() {
    local port=$1
    local name=$2

    local pids=$(lsof -ti :$port 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill 2>/dev/null
        sleep 2
        # Force kill if still running
        pids=$(lsof -ti :$port 2>/dev/null)
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill -9 2>/dev/null
        fi
        print_status "$name 중단 완료 (포트: $port)"
        return 0
    else
        print_warning "$name 이미 중단됨"
        return 1
    fi
}

stop_api() {
    echo "🛑 API 서버 중단 중..."
    stop_by_pid_file "$API_PID_FILE" "API 서버"
    stop_by_port $API_PORT "API 서버"
}

stop_ui() {
    echo "🛑 Chat UI 중단 중..."
    stop_by_pid_file "$UI_PID_FILE" "Chat UI"
    stop_by_port $UI_PORT "Chat UI"

    # Streamlit 관련 프로세스 정리
    pkill -f "streamlit run chat_ui" 2>/dev/null || true
}

stop_all() {
    stop_api
    stop_ui
}

show_status() {
    echo ""
    echo "📊 서비스 상태:"
    echo "================================"

    if lsof -Pi :$API_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "  API 서버:  ${GREEN}실행 중${NC}"
    else
        echo -e "  API 서버:  ${RED}중지됨${NC}"
    fi

    if lsof -Pi :$UI_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "  Chat UI:   ${GREEN}실행 중${NC}"
    else
        echo -e "  Chat UI:   ${RED}중지됨${NC}"
    fi

    echo "================================"
}

# 메인 로직
case "${1:-all}" in
    api)
        stop_api
        ;;
    ui)
        stop_ui
        ;;
    all)
        stop_all
        show_status
        ;;
    *)
        echo "Usage: $0 [all|api|ui]"
        echo ""
        echo "Options:"
        echo "  all  - API 서버와 Chat UI 모두 중단 (기본값)"
        echo "  api  - API 서버만 중단"
        echo "  ui   - Chat UI만 중단"
        exit 1
        ;;
esac
