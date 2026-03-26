import { useState } from 'react'
import { Bot, Mail, Loader2, ChevronUp, ChevronDown, X, StopCircle, CheckCircle2 } from 'lucide-react'

export interface TaskState {
  searching: boolean
  searchLog: string[]
  composing: boolean
  composeLog: string[]
  onStopSearch: () => void
  onStopCompose: () => void
  onOpenSearchModal: () => void
}

export default function GlobalTaskIndicator({
  searching, searchLog, composing, composeLog,
  onStopSearch, onStopCompose, onOpenSearchModal,
}: TaskState) {
  const [expanded, setExpanded] = useState(true)
  const [dismissed, setDismissed] = useState(false)

  const hasActivity = searching || composing
  const hasLogs = searchLog.length > 0 || composeLog.length > 0

  // Nothing to show
  if (!hasActivity && !hasLogs) return null
  // User dismissed after tasks done
  if (dismissed && !hasActivity) return null
  // Reset dismissed if a new task starts
  if (dismissed && hasActivity) setDismissed(false)

  const lastSearchMsg = searchLog[searchLog.length - 1] || ''
  const lastComposeMsg = composeLog[composeLog.length - 1] || ''

  return (
    <div className="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-2">
      {/* Expanded panel */}
      {expanded && (hasActivity || hasLogs) && (
        <div className="w-96 rounded-2xl bg-white shadow-2xl border border-gray-200 overflow-hidden animate-in slide-in-from-bottom-4">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-100">
            <span className="text-sm font-semibold text-gray-700">后台任务</span>
            <div className="flex items-center gap-1">
              <button onClick={() => setExpanded(false)} className="p-1 rounded hover:bg-gray-200 text-gray-400">
                <ChevronDown className="h-4 w-4" />
              </button>
              {!hasActivity && (
                <button onClick={() => setDismissed(true)} className="p-1 rounded hover:bg-gray-200 text-gray-400">
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>

          {/* Search task */}
          {(searching || searchLog.length > 0) && (
            <div className="px-4 py-3 border-b border-gray-50">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  {searching ? (
                    <Loader2 className="h-4 w-4 text-indigo-500 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4 text-green-500" />
                  )}
                  <span className="text-sm font-medium text-gray-800">
                    {searching ? 'Agent 搜索中' : '搜索完成'}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  {searching && (
                    <button
                      onClick={onStopSearch}
                      className="rounded px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                    >
                      终止
                    </button>
                  )}
                  <button
                    onClick={onOpenSearchModal}
                    className="rounded px-2 py-0.5 text-xs text-indigo-600 hover:bg-indigo-50"
                  >
                    详情
                  </button>
                </div>
              </div>
              <p className="text-xs text-gray-500 truncate">{lastSearchMsg}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">{searchLog.length} 条日志</p>
            </div>
          )}

          {/* Compose task */}
          {(composing || composeLog.length > 0) && (
            <div className="px-4 py-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  {composing ? (
                    <Loader2 className="h-4 w-4 text-purple-500 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4 text-green-500" />
                  )}
                  <span className="text-sm font-medium text-gray-800">
                    {composing ? '生成邮件中' : '邮件生成完成'}
                  </span>
                </div>
                {composing && (
                  <button
                    onClick={onStopCompose}
                    className="rounded px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                  >
                    终止
                  </button>
                )}
              </div>
              <p className="text-xs text-gray-500 truncate">{lastComposeMsg}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">{composeLog.length} 条日志</p>
            </div>
          )}
        </div>
      )}

      {/* Collapsed pill — always visible when there's activity */}
      {(!expanded || !hasActivity) && hasActivity && (
        <button
          onClick={() => setExpanded(true)}
          className="flex items-center gap-2 rounded-full bg-indigo-600 pl-3 pr-4 py-2.5 text-white shadow-lg hover:bg-indigo-700 transition-colors"
        >
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-sm font-medium">
            {searching && composing
              ? '搜索 + 生成中'
              : searching
              ? 'Agent 搜索中'
              : '生成邮件中'}
          </span>
          <ChevronUp className="h-3.5 w-3.5 ml-1" />
        </button>
      )}
    </div>
  )
}
