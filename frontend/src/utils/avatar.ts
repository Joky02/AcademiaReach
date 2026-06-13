// 姓名 → 稳定彩色渐变（同一个人每次都是同色），用于头像背景
// 渐变 class 必须是字面量字符串，Tailwind JIT 才能扫到 — 别动 PALETTE 数组里的字符串结构

const PALETTE = [
  'from-indigo-400 to-purple-500',
  'from-emerald-400 to-teal-500',
  'from-rose-400 to-pink-500',
  'from-amber-400 to-orange-500',
  'from-sky-400 to-blue-500',
  'from-fuchsia-400 to-purple-500',
  'from-lime-400 to-green-500',
  'from-violet-400 to-indigo-500',
  'from-cyan-400 to-blue-500',
  'from-red-400 to-rose-500',
  'from-teal-400 to-cyan-500',
  'from-pink-400 to-rose-500',
]

function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h) + s.charCodeAt(i)
    h |= 0
  }
  return Math.abs(h)
}

export function nameToGradient(name: string): string {
  if (!name) return PALETTE[0]
  return PALETTE[hashStr(name) % PALETTE.length]
}

// 中文姓名取前两个字；英文取首尾词首字母
export function getInitials(name: string): string {
  if (!name) return '?'
  const trimmed = name.trim()
  if (/[一-鿿]/.test(trimmed)) {
    return trimmed.slice(0, 2)
  }
  const parts = trimmed.split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0][0].toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
