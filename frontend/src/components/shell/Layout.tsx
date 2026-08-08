/**
 * Page shell: header, `main#content`, footer.
 *
 * `main` is the skip-link target and the only element that grows, so the footer
 * sits at the bottom of short pages. Horizontal overflow is clipped here as a
 * backstop: wide tables and charts must scroll inside their own container, and
 * the page itself never does.
 */

import type { ReactNode } from 'react'
import Header from '@/components/shell/Header'
import Footer from '@/components/shell/Footer'
import WebAnalyticsBeacon from '@/components/shell/WebAnalyticsBeacon'

export interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="flex min-h-screen flex-col overflow-x-clip bg-surface-page">
      <Header />
      <main id="content" tabIndex={-1} className="flex-1 focus:outline-none">
        <div className="mx-auto w-full max-w-shell px-5 py-10 sm:px-8 sm:py-16">{children}</div>
      </main>
      <Footer />
      <WebAnalyticsBeacon />
    </div>
  )
}
