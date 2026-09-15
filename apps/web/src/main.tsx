import React from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { App } from './App'
import './styles.css'

const theme = localStorage.getItem('paa.company.theme') || 'system'
document.documentElement.dataset.theme =
  theme === 'system'
    ? matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light'
    : theme
const router = createBrowserRouter([{ path: '*', element: <App /> }])
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)

matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (event) => {
  if ((localStorage.getItem('paa.company.theme') || 'system') === 'system')
    document.documentElement.dataset.theme = event.matches ? 'dark' : 'light'
})
