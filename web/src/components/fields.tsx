import type { ReactNode } from 'react'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

/** A labelled setting, with an optional hint below it. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-sm text-muted-foreground">{hint}</span>}
    </div>
  )
}

interface NumberSelectProps {
  value: number
  options: number[]
  label: (value: number) => string
  onChange: (value: number) => void
}

/** A choice of numbers; a saved value that isn't among the options is still shown. */
export function NumberSelect({ value, options, label, onChange }: NumberSelectProps) {
  const all = options.includes(value) ? options : [...options, value].sort((a, b) => a - b)
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(Number(v))}>
      <SelectTrigger className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {all.map((option) => (
          <SelectItem key={option} value={String(option)}>
            {label(option)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
