import { useEffect, useRef, useState } from 'react'

interface AnimatedNumberProps {
  value: number
  locale?: string
  duration?: number
}

/** Counts once, when visible. The final value remains available to assistive technology. */
export default function AnimatedNumber({ value, locale = 'es-CL', duration = 900 }: AnimatedNumberProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const [displayed, setDisplayed] = useState(0)
  const [started, setStarted] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node || started) return
    if (!('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setDisplayed(value)
      setStarted(true)
      return
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setStarted(true)
      },
      { threshold: 0.35 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [started, value])

  useEffect(() => {
    if (!started) return
    let frame = 0
    const initial = performance.now()
    const tick = (now: number) => {
      const progress = Math.min((now - initial) / duration, 1)
      const eased = 1 - (1 - progress) ** 3
      setDisplayed(Math.round(value * eased))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [duration, started, value])

  return (
    <span ref={ref}>
      <span className="sr-only">{value.toLocaleString(locale)}</span>
      <span aria-hidden="true">{displayed.toLocaleString(locale)}</span>
    </span>
  )
}
