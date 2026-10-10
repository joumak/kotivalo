import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useLiveValue } from './use-live-value'

describe('useLiveValue', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('sends at most every 200 ms while dragging, then the final value', () => {
    const send = vi.fn()
    const { result } = renderHook(() => useLiveValue(10, send))

    act(() => {
      for (let v = 11; v <= 30; v++) {
        result.current.change(v)
        vi.advanceTimersByTime(20) // 20 values over 400 ms
      }
    })
    expect(send.mock.calls.length).toBeLessThanOrEqual(3)
    expect(result.current.value).toBe(30)

    act(() => result.current.commit(31))
    expect(send).toHaveBeenLastCalledWith(31)
  })

  it('ignores pushed values while dragging, and follows them afterwards', () => {
    const send = vi.fn()
    let remote = 10
    const { result, rerender } = renderHook(() => useLiveValue(remote, send))
    act(() => result.current.change(50))
    remote = 20 // an older state pushed by the server mid-drag
    rerender()
    expect(result.current.value).toBe(50)

    act(() => {
      result.current.commit(55)
      vi.advanceTimersByTime(2000)
    })
    remote = 55
    rerender()
    expect(result.current.value).toBe(55)
  })
})
