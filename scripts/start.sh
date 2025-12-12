#!/bin/bash
#
# R-Agent 서비스 시작 스크립트
# Usage: ./start.sh [all|api|ui]
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

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

check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port in use
    else
        return 1  # Port free
    fi
}

start_api() {
    echo "🚀 API 서버 시작 중..."

    if check_port $API_PORT; then
        print_warning "API 서버가 이미 실행 중입니다 (포트: $API_PORT)"
        return 1
    fi

    cd "$PROJECT_DIR"

    # API 서버 시작
    nohup python3 -m uvicorn api.main:app \
        --host 0.0.0.0 \
        --port $API_PORT \
        > "$LOG_DIR/api.log" 2>&1 &

    API_PID=$!
    echo $API_PID > "$API_PID_FILE"

    # 시작 대기 (최대 10초)
    for i in {1..10}; do
        sleep 1
        if check_port $API_PORT; then
            break
        fi
    done

    if check_port $API_PORT; then
        print_status "API 서버 시작 완료 (PID: $API_PID, 포트: $API_PORT)"
        return 0
    else
        print_error "API 서버 시작 실패"
        rm -f "$API_PID_FILE"
        return 1
    fi
}

start_ui() {
    echo "🚀 Chat UI 시작 중..."

    if check_port $UI_PORT; then
        print_warning "Chat UI가 이미 실행 중입니다 (포트: $UI_PORT)"
        return 1
    fi

    cd "$PROJECT_DIR"

    # Streamlit UI 시작
    nohup streamlit run chat_ui_prod.py \
        --server.port $UI_PORT \
        --server.address 0.0.0.0 \
        --server.headless true \
        > "$LOG_DIR/ui.log" 2>&1 &

    UI_PID=$!
    echo $UI_PID > "$UI_PID_FILE"

    # 시작 대기
    sleep 5

    if check_port $UI_PORT; then
        print_status "Chat UI 시작 완료 (PID: $UI_PID, 포트: $UI_PORT)"
        return 0
    else
        print_error "Chat UI 시작 실패"
        rm -f "$UI_PID_FILE"
        return 1
    fi
}

show_status() {
    echo ""
    echo "📊 서비스 상태:"
    echo "================================"

    if check_port $API_PORT; then
        echo -e "  API 서버:  ${GREEN}실행 중${NC} (http://0.0.0.0:$API_PORT)"
    else
        echo -e "  API 서버:  ${RED}중지됨${NC}"
    fi

    if check_port $UI_PORT; then
        echo -e "  Chat UI:   ${GREEN}실행 중${NC} (http://0.0.0.0:$UI_PORT)"
    else
        echo -e "  Chat UI:   ${RED}중지됨${NC}"
    fi

    echo "================================"
}

# 메인 로직
case "${1:-all}" in
    api)
        start_api
        ;;
    ui)
        start_ui
        ;;
    all)
        start_api
        start_ui
        show_status
        ;;
    *)
        echo "Usage: $0 [all|api|ui]"
        echo ""
        echo "Options:"
        echo "  all  - API 서버와 Chat UI 모두 시작 (기본값)"
        echo "  api  - API 서버만 시작"
        echo "  ui   - Chat UI만 시작"
        exit 1
        ;;
esac
