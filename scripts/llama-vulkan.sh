#!/bin/bash
# Start, stop, or check the llama.cpp server on the Radeon Pro 580
# via Vulkan (MoltenVK). Usage from the repo root:
#   scripts/llama-vulkan.sh start
#   scripts/llama-vulkan.sh stop
#   scripts/llama-vulkan.sh status
# Start verifies Vulkan0 is actually listed before launching, so a
# plain -ngl run can never silently fall back to Metal again.
# The server log and PID live outside the repo, in $HOME, so they
# are never committed. Override with LLAMA_MODEL, LLAMA_SERVER_BIN,
# LLAMA_PORT, LLAMA_PID_FILE, or LLAMA_LOG_FILE.
set -euo pipefail

MODEL="${LLAMA_MODEL:-$HOME/models/qwen3-8b.gguf}"
SERVER_BIN="${LLAMA_SERVER_BIN:-$HOME/llama.cpp/build/bin/llama-server}"
PORT="${LLAMA_PORT:-8080}"
PID_FILE="${LLAMA_PID_FILE:-$HOME/.llama-vulkan.pid}"
LOG_FILE="${LLAMA_LOG_FILE:-$HOME/.llama-vulkan.log}"
BASE_URL="http://localhost:${PORT}"

set_vulkan_env() {
    if [ -d "$HOME/VulkanSDK" ]; then
        SDK_VERSION="$(ls "$HOME/VulkanSDK" | head -1)"
        export VULKAN_SDK="$HOME/VulkanSDK/${SDK_VERSION}/macOS"
        export PATH="$VULKAN_SDK/bin:$PATH"
        export VK_ADD_LAYER_PATH="$VULKAN_SDK/share/vulkan/explicit_layer.d"
        export VK_ICD_FILENAMES="$VULKAN_SDK/share/vulkan/icd.d/MoltenVK_icd.json"
        export DYLD_LIBRARY_PATH="$VULKAN_SDK/lib:${DYLD_LIBRARY_PATH:-}"
    fi
}

server_alive() {
    curl -fsS --max-time 5 "$BASE_URL/health" >/dev/null 2>&1
}

pid_alive() {
    [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

cmd_start() {
    if server_alive; then
        echo "llama-server already answering on $BASE_URL"
        exit 0
    fi
    if pid_alive; then
        echo "stale PID file found, removing it"
        rm -f "$PID_FILE"
    fi
    [ -x "$SERVER_BIN" ] || { echo "server binary not found: $SERVER_BIN"; exit 1; }
    [ -f "$MODEL" ] || { echo "model file not found: $MODEL"; exit 1; }
    set_vulkan_env
    if ! "$SERVER_BIN" --list-devices 2>/dev/null | grep -q "Vulkan0"; then
        echo "Vulkan0 not listed by --list-devices, refusing to start (would fall back to Metal)"
        "$SERVER_BIN" --list-devices || true
        exit 1
    fi
    nohup "$SERVER_BIN" -m "$MODEL" -ngl 99 --port "$PORT" --device Vulkan0 >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    echo "started llama-server PID $(cat "$PID_FILE"), log $LOG_FILE"
    for _ in $(seq 1 60); do
        if server_alive; then
            echo "healthy on $BASE_URL"
            exit 0
        fi
        sleep 2
    done
    echo "server did not become healthy within 120s, see $LOG_FILE"
    exit 1
}

cmd_stop() {
    if ! pid_alive; then
        rm -f "$PID_FILE"
        if server_alive; then
            echo "server answers on $BASE_URL but no PID file was found; find it with: ps aux | grep llama-server"
            exit 1
        fi
        echo "no llama-server running"
        exit 0
    fi
    PID="$(cat "$PID_FILE")"
    kill "$PID"
    for _ in $(seq 1 10); do
        kill -0 "$PID" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$PID" 2>/dev/null; then
        kill -9 "$PID"
    fi
    rm -f "$PID_FILE"
    echo "stopped llama-server PID $PID"
}

cmd_status() {
    if pid_alive; then
        echo "PID $(cat "$PID_FILE") running"
    else
        echo "no PID file / no live PID"
    fi
    if server_alive; then
        echo "healthy on $BASE_URL"
    else
        echo "not answering on $BASE_URL"
    fi
    if [ -f "$LOG_FILE" ]; then
        echo "log: $LOG_FILE"
    fi
}

case "${1:-}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    *) echo "usage: $0 start|stop|status"; exit 2 ;;
esac
