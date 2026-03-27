import { createBrowserRouter, RouterProvider, useLocation, Navigate, Outlet } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { Layout } from './components/layout/Layout'
import { AdminRoute } from './components/admin/AdminRoute'
import { TotpGate } from './components/admin/TotpGate'
import { HomePage } from './pages/HomePage'
import { RecipesPage } from './pages/RecipesPage'
import { RecipeDetailPage } from './pages/RecipeDetailPage'
import { AdminDashboardPage } from './pages/AdminDashboardPage'
import { AdminRecipeEditPage } from './pages/AdminRecipeEditPage'
import { AdminCategoriesPage } from './pages/AdminCategoriesPage'
import { AdminPagesPage } from './pages/AdminPagesPage'
import { AdminPageEditPage } from './pages/AdminPageEditPage'
import { AdminExpensesPage } from './pages/AdminExpensesPage'
import { AdminExpenseEditPage } from './pages/AdminExpenseEditPage'
import { AdminReportsPage } from './pages/AdminReportsPage'
import { AdminRecipePreviewPage } from './pages/AdminRecipePreviewPage'
import { AboutPage } from './pages/AboutPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { SupportPage } from './pages/SupportPage'
import { SupportSuccessPage } from './pages/SupportSuccessPage'
import { SupportCancelPage } from './pages/SupportCancelPage'

function EnsureTrailingSlash() {
  const { pathname, search, hash } = useLocation()
  if (!pathname.endsWith('/')) {
    return <Navigate to={`${pathname}/${search}${hash}`} replace />
  }
  return <Outlet />
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
])

export function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}
