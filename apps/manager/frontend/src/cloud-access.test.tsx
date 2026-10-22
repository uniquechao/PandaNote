// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act} from 'react'
import {createRoot,type Root} from 'react-dom/client'
import {CloudAccess} from './CloudAccess'
import {CalDAVSources} from './CalDAVSources'
import {setCsrfToken} from './api'
let root:Root,host:HTMLDivElement
beforeEach(()=>{history.replaceState(null,'','/pandanote/');document.head.innerHTML='<meta name="app-prefix" content="/pandanote"><meta name="cloud-profile" content="true">';vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host)})
afterEach(async()=>{await act(async()=>root.unmount());host.remove();document.head.innerHTML='';setCsrfToken('');vi.unstubAllGlobals()})
it('renders no private manager content before login and removes it on expiry',async()=>{
 let authorized=false
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify(authorized?{ok:true,username:'admin',csrf_token:'fixture'}:{ok:false,error:{message:'login'}}),{status:authorized?200:401}))
 await act(async()=>{root.render(<CloudAccess><span>private-manager-content</span></CloudAccess>);await new Promise(r=>setTimeout(r,10))})
 expect(host.textContent).toContain('重要的事');expect(host.textContent).not.toContain('private-manager-content')
 await act(async()=>root.unmount());root=createRoot(host);authorized=true
 await act(async()=>{root.render(<CloudAccess><span>private-manager-content</span></CloudAccess>);await new Promise(r=>setTimeout(r,10))})
 expect(host.textContent).toContain('private-manager-content')
 await act(async()=>window.dispatchEvent(new Event('pandanote-auth-expired')))
 expect(host.textContent).not.toContain('private-manager-content');expect(host.querySelector('input[type=password]')?.getAttribute('value')).toBe('')
})
it('editing a CalDAV source with blank password preserves the stored secret and uses its own source id',async()=>{
 const source={id:'source_one',label:'工作',url:'https://calendar.example.com/',username:'fixture-user',enabled:true,has_password:true,configured:true};const saved:{path:string,body:any}[]=[]
 vi.stubGlobal('fetch',async(path:string,options:RequestInit)=>{if(options.method==='PUT'){saved.push({path,body:JSON.parse(options.body as string)});return new Response(JSON.stringify({ok:true,source}))}return new Response(JSON.stringify({ok:true,sources:[source]}))})
 await act(async()=>{root.render(<CalDAVSources onChanged={async()=>{}}/>);await new Promise(r=>setTimeout(r,10))})
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='编辑')!.click())
 expect((host.querySelector('#caldav-password') as HTMLInputElement).value).toBe('')
 await act(async()=>{host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,10))})
 expect(saved.length).toBe(1);expect(saved[0].path).toBe('/pandanote/api/caldav/sources/source_one');expect(saved[0].body).not.toHaveProperty('password');expect(saved[0].body.label).toBe('工作')
 expect(host.querySelector('form')).toBeNull()
})
it('keeps add-source form hidden until explicitly opened',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({ok:true,sources:[]})))
 await act(async()=>{root.render(<CalDAVSources onChanged={async()=>{}}/>);await new Promise(r=>setTimeout(r,10))})
 expect(host.querySelector('form')).toBeNull()
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent?.includes('添加日历'))!.click())
 expect(host.querySelector('dialog')).not.toBeNull();expect(host.querySelector('#caldav-url')).not.toBeNull()
})
