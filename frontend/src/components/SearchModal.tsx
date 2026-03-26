import { useEffect, useRef } from 'react'
import { X, StopCircle, Bot, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'

interface Props {
  open: boolean
  logs: string[]
  searching: boolean
  onClose: () => void
  onStop: () => void
}

export default function SearchModal({ open, logs, searching, onClose, onStop }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="relative flex h-[80vh] w-[90vw] max-w-3xl flex-col rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-100">
              <Bot className="h-5 w-5 text-indigo-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Agent 搜索导师</h2>
              <p className="text-xs text-gray-500">
                {searching ? 'Agent 正在自主搜索中...' : '搜索已结束'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {searching && (
              <button
                onClick={onStop}
                className="inline-flex items-center gap-1.5 rounded-lg bg-red-50 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-100 transition-colors"
              >
                <StopCircle className="h-4 w-4" />
                终止搜索
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Log area */}
        <div className="flex-1 overflow-y-auto px-6 py-4 bg-gray-50/50">
          <div className="space-y-2">
            {logs.length === 0 && (
              <div className="flex items-center justify-center h-full text-gray-400 text-sm py-20">
                等待 Agent 开始...
              </div>
            )}
            {logs.map((msg, i) => {
              const isRound = msg.startsWith('═══')
              const isError = msg.includes('失败') || msg.includes('出错') || msg.includes('终止')
              const isAnalysis = msg.startsWith('Agent 分析:')
              const isDone = msg.includes('停止搜索') || msg.includes('已达到目标')
              const isQuery = msg.startsWith('搜索 (')

              if (isRound) {
                return (
                  <div key={i} className="flex items-center gap-3 pt-4 pb-2">
                    <div className="h-px flex-1 bg-indigo-200" />
                    <span className="text-xs font-bold text-indigo-500 whitespace-nowrap">{msg}</span>
                    <div className="h-px flex-1 bg-indigo-200" />
                  </div>
                )
              }

              return (
                <div
                  key={i}
                  className={`flex items-start gap-2.5 rounded-lg px-3 py-2 text-sm ${
                    isError
                      ? 'bg-red-50 text-red-700'
                      : isAnalysis
                      ? 'bg-indigo-50 text-indigo-800'
                      : isDone
                      ? 'bg-green-50 text-green-700'
                      : isQuery
                      ? 'bg-white text-gray-600 border border-gray-100'
                      : 'text-gray-600'
                  }`}
                >
                  <span className="mt-0.5 shrink-0">
                    {isError ? (
                      <AlertCircle className="h-3.5 w-3.5 text-red-400" />
                    ) : isAnalysis ? (
                      <Bot className="h-3.5 w-3.5 text-indigo-500" />
                    ) : isDone ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                    ) : (
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-gray-300 mt-1" />
                    )}
                  </span>
                  <span className="leading-relaxed">{msg}</span>
                </div>
              )
            })}
            {searching && (
              <div className="flex items-center gap-2 px-3 py-2 text-sm text-indigo-500">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>处理中...</span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-gray-100 px-6 py-3 flex items-center justify-between">
          <p className="text-xs text-gray-400">
            共 {logs.length} 条日志
          </p>
          {!searching && (
            <button
              onClick={onClose}
              className="rounded-lg bg-indigo-600 px-6 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
            >
              完成
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
