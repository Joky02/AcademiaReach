import { useState, useEffect } from 'react'
import { Send, Loader2, Clock, CheckCircle2 } from 'lucide-react'
import { getDrafts } from '../services/api'

export default function Sent() {
  const [sentEmails, setSentEmails] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getDrafts('sent')
      .then((res) => setSentEmails(res.data))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">发送状态</h2>

      {loading ? (
        <div className="flex items-center justify-center p-12">
          <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
        </div>
      ) : sentEmails.length === 0 ? (
        <div className="rounded-xl bg-white p-12 text-center shadow-sm border border-gray-100">
          <Send className="mx-auto h-12 w-12 text-gray-300" />
          <p className="mt-4 text-gray-500">暂无已发送邮件</p>
        </div>
      ) : (
        <div className="rounded-xl bg-white shadow-sm border border-gray-100 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                {['收件人', '学校', '邮件主题', '发送时间', '状态'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sentEmails.map((e) => (
                <tr key={e.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-gray-900">{e.professor_name}</div>
                    <div className="text-xs text-gray-500">{e.professor_email}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{e.professor_university}</td>
                  <td className="px-4 py-3 text-sm text-gray-800 max-w-xs truncate">{e.subject}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    <div className="flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5" />
                      {e.sent_at ? new Date(e.sent_at).toLocaleString('zh-CN') : '-'}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                      <CheckCircle2 className="h-3 w-3" />
                      已发送
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
