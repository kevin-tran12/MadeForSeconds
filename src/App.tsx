import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { Layout } from './components/layout/Layout'
import { AdminRoute } from './components/admin/AdminRoute'
import { TotpGate } from './components/admin/TotpGate'
import { HomePage } from './pages/HomePage'
import { RecipesPage } from './pages/RecipesPage'
import { RecipeDetailPage } from './pages/RecipeDetailPage'
import { AdminDashboardPage } from './pages/AdminDashboardPage'
import { AdminRecipeEditPage } from './pages/AdminRecipeEditPage'
import { AdminExpensesPage } from './pages/AdminExpensesPage'
import { AdminExpenseEditPage } from './pages/AdminExpenseEditPage'
import { AdminReportsPage } from './pages/AdminReportsPage'
import { AboutPage } from './pages/AboutPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { SupportPage } from './pages/SupportPage'
import { SupportSuccessPage } from './pages/SupportSuccessPage'
import { SupportCancelPage } from './pages/SupportCancelPage'

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    errorElement: <NotFoundPage />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'recipes', element: <RecipesPage /> },
      { path: 'recipes/:slug', element: <RecipeDetailPage /> },
      { path: 'about', element: <AboutPage /> },
      { path: 'support', element: <SupportPage /> },
      { path: 'support/success', element: <SupportSuccessPage /> },
      { path: 'support/cancel', element: <SupportCancelPage /> },
      {
        path: 'admin',
        element: <AdminRoute />,
        children: [
          { index: true, element: <AdminDashboardPage /> },
          { path: 'new', element: <AdminRecipeEditPage /> },
          { path: 'edit/:id', element: <AdminRecipeEditPage /> },
          {
            element: <TotpGate />,
            children: [
              { path: 'expenses', element: <AdminExpensesPage /> },
              { path: 'expenses/new', element: <AdminExpenseEditPage /> },
              { path: 'expenses/reports', element: <AdminReportsPage /> },
              { path: 'expenses/:id', element: <AdminExpenseEditPage /> },
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
