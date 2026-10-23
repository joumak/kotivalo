import { useMemo } from 'react'
import { toast } from 'sonner'

import { useT } from '@/i18n'

import { ApiError, api } from './client'
import { useLiveState } from './live'
import type { Snapshot } from './types'

/**
 * The API, wired to the live state (responses update every view at once) and to
 * error toasts. Each call resolves to true on success.
 */
export function useActions() {
  const live = useLiveState()
  const t = useT()

  return useMemo(() => {
    const run = async (call: Promise<Snapshot>): Promise<boolean> => {
      try {
        live.apply(await call)
        return true
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        if (error.status === 0) toast.error(t.error.unreachable)
        else if (error.status === 502) toast.error(t.error.lamp)
        else toast.error(t.error.generic(error.message))
        return false
      }
    }
    return {
      lamp: (...args: Parameters<typeof api.lamp>) => run(api.lamp(...args)),
      refreshLamp: (ieee: string) => run(api.refreshLamp(ieee)),
      wakeup: (change: Parameters<typeof api.wakeup>[0]) => run(api.wakeup(change)),
      night: (start: string, end: string) => run(api.night(start, end)),
      daylight: (curve: Parameters<typeof api.daylight>[0]) => run(api.daylight(curve)),
      device: (ieee: string, change: Parameters<typeof api.device>[1]) => run(api.device(ieee, change)),
      removeDevice: (ieee: string) => run(api.removeDevice(ieee)),
      motion: (sensor: string, rule: Parameters<typeof api.motion>[1]) => run(api.motion(sensor, rule)),
      removeMotion: (sensor: string) => run(api.removeMotion(sensor)),
      remote: (remote: string, lights: string[]) => run(api.remote(remote, lights)),
      updateFirmware: (remote: string) => run(api.updateFirmware(remote)),
      skip: (key: string, skip: boolean) => run(api.skip(key, skip)),
      testSunrise: (minutes: number) => run(api.testSunrise(minutes)),
      stopSunrise: () => run(api.stopSunrise()),
      permit: (seconds: number) => run(api.permit(seconds)),
      weather: (place: Parameters<typeof api.weather>[0]) => run(api.weather(place)),
      master: (...args: Parameters<typeof api.master>) => run(api.master(...args)),
      createFixture: (fixture: Parameters<typeof api.createFixture>[0]) => run(api.createFixture(fixture)),
      updateFixture: (ieee: string, members: string[]) => run(api.updateFixture(ieee, members)),
    }
  }, [live, t])
}
