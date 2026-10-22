import {create} from 'zustand'
import {createContext,useContext} from 'react'
import type {Crop} from './image'
type Message={text:string;error:boolean}
type State={draftZone:string;draftIds:string[];crop:Crop;layout:Record<string,number>;loading:string|null;messages:Record<string,Message>;setDraft:(zone:string,ids:string[])=>void;setCrop:(crop:Crop)=>void;setLayout:(layout:Record<string,number>)=>void;message:(key:string,text:string,error?:boolean)=>void;run:(key:string,fn:()=>Promise<void>)=>Promise<void>}
// In-memory interaction state only: no persist middleware, cookies, credentials,
// or private event payloads in local/session storage.
export const createManagerStore=()=>create<State>((set)=>({
  draftZone:'',draftIds:[],crop:{x:0,y:0,width:480,height:800},layout:{config:54,preview:46},loading:null,messages:{},
  setDraft:(draftZone,draftIds)=>set({draftZone,draftIds}),setCrop:crop=>set({crop}),setLayout:layout=>set({layout}),
  message:(key,text,error=false)=>set(state=>({messages:{...state.messages,[key]:{text,error}}})),
  run:async(key,fn)=>{set({loading:key});try{await fn()}catch(error){set(state=>({messages:{...state.messages,[key]:{text:error instanceof Error?error.message:'操作失败。',error:true}}}))}finally{set({loading:null})}},
}))

export const useManager=createManagerStore()
export const ManagerContext=createContext<ReturnType<typeof createManagerStore>|null>(null)
export function useDeviceManager<T=State>(selector?: (state:State)=>T):T{const store=useContext(ManagerContext)||useManager;return store(selector||((state)=>state as T))}
