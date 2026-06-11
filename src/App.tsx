import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider, useLocation, Navigate, Outlet } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { Layout } from './components/layout/Layout'
import { AdminRoute } from './components/admin/AdminRoute'
import { TotpGate } from './components/admin/TotpGate'
import { LoadingSpinner } from './components/ui/LoadingSpinner'
import { HomePage } from './pages/HomePage'
import { RecipesPage } from './pages/RecipesPage'
import { RecipeDetailPage } from './pages/RecipeDetailPage'
import { AboutPage } from './pages/AboutPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { SupportPage } from './pages/SupportPage'
import { SupportSuccessPage } from './pages/SupportSuccessPage'
import { SupportCancelPage } from './pages/SupportCancelPage'

// Admin pages are lazy-loaded so the editor/expenses/reports code never ships
// to public visitors
const AdminDashboardPage = lazy(() => import('./pages/AdminDashboardPage').then((m) => ({ default: m.AdminDashboardPage })))
const AdminRecipeEditPage = lazy(() => import('./pages/AdminRecipeEditPage').then((m) => ({ default: m.AdminRecipeEditPage })))
const AdminRecipePreviewPage = lazy(() => import('./pages/AdminRecipePreviewPage').then((m) => ({ default: m.AdminRecipePreviewPage })))
const AdminCategoriesPage = lazy(() => import('./pages/AdminCategoriesPage').then((m) => ({ default: m.AdminCategoriesPage })))
const AdminPagesPage = lazy(() => import('./pages/AdminPagesPage').then((m) => ({ default: m.AdminPagesPage })))
const AdminPageEditPage = lazy(() => import('./pages/AdminPageEditPage').then((m) => ({ default: m.AdminPageEditPage })))
const AdminExpensesPage = lazy(() => import('./pages/AdminExpensesPage').then((m) => ({ default: m.AdminExpensesPage })))
const AdminExpenseEditPage = lazy(() => import('./pages/AdminExpenseEditPage').then((m) => ({ default: m.AdminExpenseEditPage })))
const AdminReportsPage = lazy(() => import('./pages/AdminReportsPage').then((m) => ({ default: m.AdminReportsPage })))

function EnsureTrailingSlash() {
  const { pathname, search, hash } = useLocation()
  if (!pathname.endsWith('/')) {
    return <Navigate to={`${pathname}/${search}${hash}`} replace />
  }
  return <Outlet />
}

function AdminSuspense() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-20">
          <LoadingSpinner />
        </div>
      }
    >
      <Outlet />
    </Suspense>
  )
}

const router = createBrowserRouter([
  {
    element: <EnsureTrailingSlash />,
    children: [
      {
        path: '/',
        element: <Layout />,
        errorElement: <NotFoundPage />,
        children: [
          { index: true, element: <HomePage /> },
          { path: 'recipes/', element: <RecipesPage /> },
          { path: 'recipes/:slug/', element: <RecipeDetailPage /> },
          { path: 'about/', element: <AboutPage /> },
          { path: 'support/', element: <SupportPage /> },
          { path: 'support/success/', element: <SupportSuccessPage /> },
          { path: 'support/cancel/', element: <SupportCancelPage /> },
          {
            path: 'admin/',
            element: <AdminRoute />,
            children: [
              {
                element: <AdminSuspense />,
                children: [
                  { index: true, element: <AdminDashboardPage /> },
                  { path: 'new/', element: <AdminRecipeEditPage /> },
                  { path: 'edit/:id/', element: <AdminRecipeEditPage /> },
                  { path: 'preview/:id/', element: <AdminRecipePreviewPage /> },
                  { path: 'categories/', element: <AdminCategoriesPage /> },
                  { path: 'pages/', element: <AdminPagesPage /> },
                  { path: 'pages/:pageId/', element: <AdminPageEditPage /> },
                  {
                    element: <TotpGate />,
                    children: [
                      { path: 'expenses/', element: <AdminExpensesPage /> },
                      { path: 'expenses/new/', element: <AdminExpenseEditPage /> },
                      { path: 'expenses/reports/', element: <AdminReportsPage /> },
                      { path: 'expenses/:id/', element: <AdminExpenseEditPage /> },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
])

export function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}
