import { useEffect } from 'react'

/**
 * Optional privacy-first traffic beacon. The public site token identifies the
 * Cloudflare Web Analytics property; API credentials never enter the bundle.
 */
export default function WebAnalyticsBeacon() {
  useEffect(() => {
    const token = import.meta.env.VITE_CLOUDFLARE_WEB_ANALYTICS_TOKEN?.trim()
    if (!token) return

    const script = document.createElement('script')
    script.defer = true
    script.src = 'https://static.cloudflareinsights.com/beacon.min.js'
    script.dataset.cfBeacon = JSON.stringify({ token })
    document.body.append(script)
    return () => script.remove()
  }, [])

  return null
}
