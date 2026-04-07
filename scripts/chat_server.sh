#!/bin/bash
# Chat Server (8003) 관리 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="/tmp/chat_server.pid"
LOG_FILE="/tmp/chat_server.log"
PORT=8003
PYTHON="$SCRIPT_DIR/venv/bin/python"

# 포트 사용 중인 모든 프로세스 종료
kill_by_port() {
    local pids=$(lsof -t -i :$PORT 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "Killing processes on port $PORT: $pids"
        echo "$pids" | xargs kill -9 2>/dev/null
        sleep 1
    fi
}

# 포트가 사용 가능할 때까지 대기
wait_for_port_free() {
    local max_wait=10
    local count=0
    while lsof -i :$PORT >/dev/null 2>&1; do
        if [ $count -ge $max_wait ]; then
            echo "Port $PORT still in use after ${max_wait}s"
            return 1
        fi
        sleep 1
        ((count++))
    done
    return 0
}

start() {
    # 이미 실행 중인지 확인
    if lsof -i :$PORT >/dev/null 2>&1; then
        echo "Chat server already running on port $PORT"
        lsof -i :$PORT | grep LISTEN
        return 1
    fi

    echo "Starting chat server on port $PORT..."
    nohup "$PYTHON" -m uvicorn api.main:app --host 0.0.0.0 --port $PORT > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 5

    if lsof -i :$PORT >/dev/null 2>&1; then
        echo "Chat server started (PID: $(cat $PID_FILE))"
        echo "Log: $LOG_FILE"
    else
        echo "Failed to start chat server"
        rm -f "$PID_FILE"
        tail -10 "$LOG_FILE"
        return 1
    fi
}

stop() {
    echo "Stopping chat server..."

    # 1. PID 파일로 종료 시도
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            echo "Killing PID $PID from PID file..."
            kill $PID 2>/dev/null
            sleep 2
        fi
        rm -f "$PID_FILE"
    fi

    # 2. 패턴 매칭으로 모든 관련 프로세스 종료 (--reload 자식 포함)
    local pids=$(pgrep -f "uvicorn.*api.main.*$PORT" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "Killing uvicorn processes: $pids"
        echo "$pids" | xargs kill 2>/dev/null
        sleep 2
    fi

    # 3. 강제 종료 (아직 남아있으면)
    pids=$(pgrep -f "uvicorn.*api.main.*$PORT" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "Force killing: $pids"
        echo "$pids" | xargs kill -9 2>/dev/null
        sleep 1
    fi

    # 4. 포트 기반 강제 종료 (최후의 수단)
    if lsof -i :$PORT >/dev/null 2>&1; then
        echo "Port $PORT still in use, force killing by port..."
        kill_by_port
    fi

    # 5. 포트 해제 확인
    if wait_for_port_free; then
        echo "Chat server stopped"
    else
        echo "WARNING: Could not fully stop chat server"
        lsof -i :$PORT
        return 1
    fi
}

restart() {
    stop
    sleep 1
    start
}

status() {
    if lsof -i :$PORT >/dev/null 2>&1; then
        echo "Chat server running on port $PORT"
        lsof -i :$PORT | grep LISTEN
        echo ""
        echo "Processes:"
        pgrep -af "uvicorn.*api.main.*$PORT"
        echo ""
        echo "Log: $LOG_FILE"
    else
        echo "Chat server not running"
    fi
}

logs() {
    tail -f "$LOG_FILE"
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
