#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${TAOCI_CODEX_RUNTIME_DIR:-/tmp/taoci-codex-$(id -u)}"
VENV_DIR="${TAOCI_CODEX_VENV:-${ROOT}/.run/codex-venv}"
SOCKET_PATH="${TAOCI_CODEX_SOCKET_HOST:-${RUNTIME_DIR}/worker.sock}"
WORKSPACE_DIR="${RUNTIME_DIR}/workspace"
PID_FILE="${RUNTIME_DIR}/worker.pid"
LOG_FILE="${RUNTIME_DIR}/worker.log"
PYTHON_BIN="${TAOCI_CODEX_PYTHON:-python3}"

worker_pid() {
  if [[ -f "${PID_FILE}" ]]; then
    tr -d '[:space:]' < "${PID_FILE}"
  fi
}

is_running() {
  local pid
  pid="$(worker_pid)"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    return 1
  fi
  [[ -r "/proc/${pid}/cmdline" ]] \
    && [[ "$(tr '\0' ' ' < "/proc/${pid}/cmdline")" == *"codex_worker.server"* ]]
}

install_worker() {
  mkdir -p "${RUNTIME_DIR}"
  chmod 700 "${RUNTIME_DIR}"
  mkdir -p "${WORKSPACE_DIR}"
  chmod 700 "${WORKSPACE_DIR}"
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -r "${ROOT}/codex_worker/requirements.txt"
}

start_worker() {
  mkdir -p "${RUNTIME_DIR}"
  chmod 700 "${RUNTIME_DIR}"
  mkdir -p "${WORKSPACE_DIR}"
  chmod 700 "${WORKSPACE_DIR}"
  if is_running; then
    echo "Codex Worker is already running (PID $(worker_pid))."
    return
  fi
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    echo "Codex Worker environment is missing. Run: $0 install" >&2
    exit 1
  fi
  rm -f "${SOCKET_PATH}"
  (
    cd "${ROOT}"
    PYTHONUNBUFFERED=1 setsid "${VENV_DIR}/bin/python" -u -m codex_worker.server \
      --socket "${SOCKET_PATH}" \
      --workspace "${WORKSPACE_DIR}" \
      --concurrency "${TAOCI_CODEX_CONCURRENCY:-2}" \
      </dev/null >"${LOG_FILE}" 2>&1 &
    echo "$!" > "${PID_FILE}"
  )
  for _ in {1..20}; do
    if is_running && [[ -S "${SOCKET_PATH}" ]]; then
      break
    fi
    sleep 0.25
  done
  if ! is_running || [[ ! -S "${SOCKET_PATH}" ]]; then
    echo "Codex Worker failed to start. See ${LOG_FILE}" >&2
    exit 1
  fi
  echo "Codex Worker started (PID $(worker_pid), socket ${SOCKET_PATH})."
}

stop_worker() {
  local pid
  pid="$(worker_pid)"
  if [[ -z "${pid}" ]]; then
    rm -f "${SOCKET_PATH}"
    echo "Codex Worker is not running."
    return
  fi
  if kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}"
    for _ in {1..20}; do
      if ! is_running; then
        break
      fi
      sleep 0.25
    done
  fi
  rm -f "${PID_FILE}" "${SOCKET_PATH}"
  echo "Codex Worker stopped."
}

status_worker() {
  if is_running && [[ -S "${SOCKET_PATH}" ]]; then
    echo "Codex Worker is running (PID $(worker_pid), socket ${SOCKET_PATH})."
  else
    echo "Codex Worker is not running."
    exit 1
  fi
}

case "${1:-}" in
  install)
    install_worker
    ;;
  start)
    start_worker
    ;;
  stop)
    stop_worker
    ;;
  restart)
    stop_worker
    start_worker
    ;;
  status)
    status_worker
    ;;
  logs)
    tail -n 100 "${LOG_FILE}"
    ;;
  *)
    echo "Usage: $0 {install|start|stop|restart|status|logs}" >&2
    exit 2
    ;;
esac
