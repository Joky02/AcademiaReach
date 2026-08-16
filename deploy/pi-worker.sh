#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="${ROOT}/pi_worker"
RUNTIME_DIR="${TAOCI_PI_RUNTIME_DIR:-/tmp/taoci-pi-$(id -u)}"
SOCKET_PATH="${TAOCI_PI_SOCKET_HOST:-${RUNTIME_DIR}/worker.sock}"
WORKSPACE_DIR="${RUNTIME_DIR}/workspace"
PID_FILE="${RUNTIME_DIR}/worker.pid"
LOG_FILE="${RUNTIME_DIR}/worker.log"

bun_bin() {
  if command -v bun >/dev/null 2>&1; then
    command -v bun
  elif [[ -x "${WORKER_DIR}/node_modules/.bin/bun" ]]; then
    printf '%s\n' "${WORKER_DIR}/node_modules/.bin/bun"
  else
    return 1
  fi
}

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
  local cmdline
  [[ -r "/proc/${pid}/cmdline" ]] || return 1
  cmdline="$(tr '\0' ' ' < "/proc/${pid}/cmdline")"
  [[ "${cmdline}" == *"server.ts"*"--socket ${SOCKET_PATH}"* ]]
}

install_worker() {
  mkdir -p "${RUNTIME_DIR}" "${WORKSPACE_DIR}"
  chmod 700 "${RUNTIME_DIR}" "${WORKSPACE_DIR}"
  if ! bun_bin >/dev/null 2>&1; then
    (cd "${WORKER_DIR}" && npm install --no-package-lock)
  fi
  (cd "${WORKER_DIR}" && "$(bun_bin)" install --frozen-lockfile)
  echo "Pi Worker dependencies installed."
}

start_worker() {
  mkdir -p "${RUNTIME_DIR}" "${WORKSPACE_DIR}"
  chmod 700 "${RUNTIME_DIR}" "${WORKSPACE_DIR}"
  if is_running; then
    echo "Pi Worker is already running (PID $(worker_pid))."
    return
  fi
  if ! bun_bin >/dev/null 2>&1; then
    echo "Pi Worker dependencies are missing. Run: $0 install" >&2
    exit 1
  fi
  rm -f "${SOCKET_PATH}"
  (
    cd "${WORKER_DIR}"
    setsid "$(bun_bin)" run server.ts \
      --socket "${SOCKET_PATH}" \
      --workspace "${WORKSPACE_DIR}" \
      --concurrency "${TAOCI_PI_CONCURRENCY:-4}" \
      </dev/null >"${LOG_FILE}" 2>&1 &
    echo "$!" > "${PID_FILE}"
  )
  for _ in {1..40}; do
    if is_running && [[ -S "${SOCKET_PATH}" ]]; then
      break
    fi
    sleep 0.25
  done
  if ! is_running || [[ ! -S "${SOCKET_PATH}" ]]; then
    echo "Pi Worker failed to start. See ${LOG_FILE}" >&2
    exit 1
  fi
  echo "Pi Worker started (PID $(worker_pid), socket ${SOCKET_PATH})."
}

stop_worker() {
  local pid
  pid="$(worker_pid)"
  if [[ -z "${pid}" ]]; then
    rm -f "${SOCKET_PATH}"
    echo "Pi Worker is not running."
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
  echo "Pi Worker stopped."
}

status_worker() {
  if is_running && [[ -S "${SOCKET_PATH}" ]]; then
    echo "Pi Worker is running (PID $(worker_pid), socket ${SOCKET_PATH})."
  else
    echo "Pi Worker is not running."
    exit 1
  fi
}

case "${1:-}" in
  install) install_worker ;;
  start) start_worker ;;
  stop) stop_worker ;;
  restart) stop_worker; start_worker ;;
  status) status_worker ;;
  logs) tail -n 100 "${LOG_FILE}" ;;
  *)
    echo "Usage: $0 {install|start|stop|restart|status|logs}" >&2
    exit 2
    ;;
esac
