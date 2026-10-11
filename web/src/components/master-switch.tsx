import { Power, Timer } from 'lucide-react'

import { useActions } from '@/api/actions'
import type { Snapshot } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ButtonGroup, ButtonGroupText } from '@/components/ui/button-group'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useT } from '@/i18n'
import { MASTER_DELAYS_S, masterAction, secondsLeft } from '@/lib/master'
import { useNow } from '@/lib/screen'
import { cn } from '@/lib/utils'

interface MasterSwitchProps {
  snapshot: Snapshot
  size?: 'default' | 'lg'
  className?: string
}

/** All lamps off (remembering them), now or a few minutes later, or back on. Alarms are
 * not affected. */
export function MasterSwitch({ snapshot, size = 'default', className }: MasterSwitchProps) {
  const t = useT()
  const actions = useActions()
  const { master } = snapshot
  const now = useNow(1000)
  if (snapshot.lights.length === 0) return null

  if (master.off_at) {
    return (
      <ButtonGroup className={className}>
        <ButtonGroupText className={cn('bg-card whitespace-nowrap tabular-nums', size === 'lg' ? 'px-4 text-lg' : 'px-3 text-base')}>
          <Timer />
          {t.master.offIn(secondsLeft(master.off_at, now))}
        </ButtonGroupText>
        <Button variant="outline" size={size} onClick={() => actions.master('cancel')}>
          {t.master.cancel}
        </Button>
      </ButtonGroup>
    )
  }

  const { action, label } = masterAction(master)
  const button = (
    <Button variant="outline" size={size} onClick={() => actions.master(action)}>
      <Power data-icon="inline-start" />
      {t.master[label]}
    </Button>
  )
  if (action !== 'off') return <div className={className}>{button}</div>
  return (
    <ButtonGroup className={className}>
      {button}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size={size === 'lg' ? 'icon-lg' : 'icon'} aria-label={t.master.later}>
            <Timer />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-auto">
          <DropdownMenuLabel className={cn(size === 'lg' && 'text-base')}>{t.master.later}</DropdownMenuLabel>
          {MASTER_DELAYS_S.map((seconds) => (
            <DropdownMenuItem
              key={seconds}
              className={cn(size === 'lg' && 'min-h-12 text-lg')}
              onSelect={() => actions.master('off', seconds)}
            >
              {t.master.after(seconds / 60)}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </ButtonGroup>
  )
}
