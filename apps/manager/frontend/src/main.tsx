import {lazy,Suspense} from 'react'
import {createRoot} from 'react-dom/client'
import {CloudAccess} from './CloudAccess'
import './styles.css'
import './public.css'
import './workspace.css'
import './fleet.css'
const Workspace=lazy(()=>import('./Workspace'))
createRoot(document.getElementById('root')!).render(
  <CloudAccess><Suspense fallback={<main className="pn-session" role="status">正在打开工作台…</main>}><Workspace/></Suspense></CloudAccess>
)
