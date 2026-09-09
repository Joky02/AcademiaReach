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

is_target_worker_pid() {
  local pid="${1:-}"
  local cmdline
  if [[ -z "${pid}" ]] || [[ ! -r "/proc/${pid}/cmdline" ]]; then
    return 1
  fi
  cmdline="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null)" || return 1
  [[ "${cmdline}" == *" -m codex_worker.server "* ]] \
    && [[ "${cmdline}" == *"--socket ${SOCKET_PATH}"* ]]
}

matching_worker_pids() {
  local cmdline_path pid
  for cmdline_path in /proc/[0-9]*/cmdline; do
    [[ -r "${cmdline_path}" ]] || continue
    pid="${cmdline_path#/proc/}"
    pid="${pid%/cmdline}"
    if is_target_worker_pid "${pid}"; then
      printf '%s\n' "${pid}"
    fi
  done
}

terminate_worker_pids() {
  local pids=("$@")
  local pid pgid alive
  if [[ ${#pids[@]} -eq 0 ]]; then
    return
  fi
  for pid in "${pids[@]}"; do
    if is_target_worker_pid "${pid}"; then
      pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
      if [[ "${pgid}" == "${pid}" ]]; then
        kill -TERM -- "-${pgid}" 2>/dev/null || true
      else
        kill "${pid}" 2>/dev/null || true
      fi
    fi
  done
  for _ in {1..20}; do
    alive=0
    for pid in "${pids[@]}"; do
      if is_target_worker_pid "${pid}"; then
        alive=1
        break
      fi
    done
    [[ "${alive}" -eq 0 ]] && return
    sleep 0.25
  done
  for pid in "${pids[@]}"; do
    if is_target_worker_pid "${pid}"; then
      pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
      if [[ "${pgid}" == "${pid}" ]]; then
        kill -KILL -- "-${pgid}" 2>/dev/null || true
      else
        kill -KILL "${pid}" 2>/dev/null || true
      fi
    fi
  done
}

cleanup_orphan_workers() {
  local current pid
  local orphans=()
  current="$(worker_pid)"
  while IFS= read -r pid; do
    if [[ -n "${pid}" ]] && [[ "${pid}" != "${current}" ]]; then
      orphans+=("${pid}")
    fi
  done < <(matching_worker_pids)
  if [[ ${#orphans[@]} -gt 0 ]]; then
    terminate_worker_pids "${orphans[@]}"
    echo "Removed ${#orphans[@]} stale Codex Worker process(es)."
  fi
}

is_running() {
  local pid
  pid="$(worker_pid)"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    return 1
  fi
  is_target_worker_pid "${pid}"
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
    cleanup_orphan_workers
    echo "Codex Worker is already running (PID $(worker_pid))."
    return
  fi
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    echo "Codex Worker environment is missing. Run: $0 install" >&2
    exit 1
  fi
  local stale_pids=()
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] && stale_pids+=("${pid}")
  done < <(matching_worker_pids)
  terminate_worker_pids "${stale_pids[@]}"
  rm -f "${PID_FILE}" "${SOCKET_PATH}"
  (
    cd "${ROOT}"
    # Codex account refresh tokens are single-use; serialize App Server sessions.
    PYTHONUNBUFFERED=1 setsid "${VENV_DIR}/bin/python" -u -m codex_worker.server \
      --socket "${SOCKET_PATH}" \
      --workspace "${WORKSPACE_DIR}" \
      --concurrency "${TAOCI_CODEX_CONCURRENCY:-1}" \
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
  local pids=()
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] && pids+=("${pid}")
  done < <(matching_worker_pids)
  if [[ ${#pids[@]} -eq 0 ]]; then
    rm -f "${PID_FILE}" "${SOCKET_PATH}"
    echo "Codex Worker is not running."
    return
  fi
  terminate_worker_pids "${pids[@]}"
  rm -f "${PID_FILE}" "${SOCKET_PATH}"
  echo "Codex Worker stopped (${#pids[@]} process(es))."
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
