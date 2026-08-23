import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Footer } from './Footer'
import { SiteStatusNotice } from '../ui/SiteStatusNotice'
import { useSiteStatus } from '../../hooks/useSiteStatus'

export function Layout() {
  const siteStatus = useSiteStatus()

  return (
    <div className="flex min-h-screen flex-col">
      {siteStatus && <SiteStatusNotice status={siteStatus} />}
      <Header />
      <main className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  )
}
