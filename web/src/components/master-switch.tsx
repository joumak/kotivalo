import { Power } from 'lucide-react'

import { useActions } from '@/api/actions'
import type { Snapshot } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useT } from '@/i18n'
import { masterAction } from '@/lib/master'

interface MasterSwitchProps {
  snapshot: Snapshot
  size?: 'default' | 'lg'
  className?: string
}

/** All lamps off (remembering them), or back on. Alarms are not affected. */
export function MasterSwitch({ snapshot, size = 'default', className }: MasterSwitchProps) {
  const t = useT()
  const actions = useActions()
  if (snapshot.lights.length === 0) return null
  const { action, label } = masterAction(snapshot.master)
  return (
    <Button variant="outline" size={size} className={className} onClick={() => actions.master(action)}>
      <Power data-icon="inline-start" />
      {t.master[label]}
    </Button>
  )
}
