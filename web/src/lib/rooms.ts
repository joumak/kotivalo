import type { Lamp } from '@/api/types'

/** Lamps grouped by room, rooms in name order, unnamed room last. */
export function byRoom(lamps: Lamp[], otherLabel: string): [string, Lamp[]][] {
  const rooms = new Map<string, Lamp[]>()
  for (const lamp of lamps) {
    const room = lamp.room.trim()
    rooms.set(room, [...(rooms.get(room) ?? []), lamp])
  }
  return [...rooms.entries()]
    .sort(([a], [b]) => (a === '' ? 1 : b === '' ? -1 : a.localeCompare(b)))
    .map(([room, list]) => [room || otherLabel, list.sort((x, y) => x.name.localeCompare(y.name))])
}
