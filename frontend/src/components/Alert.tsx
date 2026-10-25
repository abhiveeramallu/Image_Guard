import type { ReactNode } from 'react'
import { AlertTriangle, CircleAlert, Info } from 'lucide-react'

const STYLES = {
  error: { cls: 'border-red-200 bg-red-50 text-red-900', Icon: CircleAlert },
  warning: { cls: 'border-amber-200 bg-amber-50 text-amber-900', Icon: AlertTriangle },
  info: { cls: 'border-sky-200 bg-sky-50 text-sky-900', Icon: Info },
}

export default function Alert({ kind = 'info', title, children, action }: {
  kind?: keyof typeof STYLES; title?: string; children?: ReactNode; action?: ReactNode
}) {
  const { cls, Icon } = STYLES[kind]
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`flex gap-3 rounded-lg border p-3 text-sm ${cls}`}>
      <Icon size={18} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}
      </div>
      {action}
    </div>
  )
}
