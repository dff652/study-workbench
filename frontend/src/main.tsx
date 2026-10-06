import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { KnowledgeFormulaTools } from './components/knowledge-formula-tools'
import './styles/index.css'

const appRoot = document.getElementById('root')
if (appRoot) ReactDOM.createRoot(appRoot).render(<React.StrictMode><App /></React.StrictMode>)
else {
  const form = document.getElementById('knowledge-form')
  const host = document.getElementById('standalone-formula-tools')
  const token = form?.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]')?.value
  if (form && host && token) ReactDOM.createRoot(host).render(<KnowledgeFormulaTools root={form} csrfToken={token} />)
}
