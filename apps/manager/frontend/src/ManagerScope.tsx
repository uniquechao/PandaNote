import {useState,type ReactNode} from 'react'
import {createManagerStore,ManagerContext} from './state'
export function ManagerScope({children}:{children:ReactNode}){const [store]=useState(createManagerStore);return <ManagerContext.Provider value={store}>{children}</ManagerContext.Provider>}
