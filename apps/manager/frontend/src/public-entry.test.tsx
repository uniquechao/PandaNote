// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act} from 'react'
import {createRoot,type Root} from 'react-dom/client'
import {CloudAccess} from './CloudAccess'
import {setCsrfToken} from './api'
let root:Root,host:HTMLDivElement
beforeEach(()=>{document.head.innerHTML='<meta name="app-prefix" content="/pandanote"><meta name="cloud-profile" content="true">';vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('scrollTo',vi.fn());history.replaceState(null,'','/pandanote/');host=document.createElement('div');document.body.append(host);root=createRoot(host)})
afterEach(async()=>{await act(async()=>root.unmount());host.remove();setCsrfToken('');vi.unstubAllGlobals()})
async function click(text:string){await act(async()=>{const b=[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,`button ${text}`).toBeTruthy();b!.click()})}
async function render(){await act(async()=>{root.render(<CloudAccess><span>private-manager-content</span></CloudAccess>);await new Promise(r=>setTimeout(r,10))})}
it('anonymous sees public product and reaches real login only through the single login menu entry',async()=>{
 const calls:string[]=[];vi.stubGlobal('fetch',async(path:string)=>{calls.push(path);return new Response(JSON.stringify({ok:false,error:{message:'请登录'}}),{status:401})});await render()
 expect(host.textContent).toContain('重要的事');expect(host.textContent).not.toContain('private-manager-content');expect(host.querySelector('input[type=password]')).toBeNull()
 await click('探索 PandaNote');expect([...host.querySelectorAll('#access-menu button')].map(b=>b.textContent)).toEqual(['登录']);await click('登录')
 expect(host.textContent).toContain('登录工作台');expect(host.querySelector('input[type=password]')).not.toBeNull();expect(calls).toEqual(['/pandanote/api/auth/session'])
})
it('successful login uses prefixed auth API and opens private workspace; expiry clears it',async()=>{
 let authorized=false;const writes:any[]=[]
 vi.stubGlobal('fetch',async(path:string,options:RequestInit)=>{if(path.endsWith('/auth/login')){writes.push(JSON.parse(options.body as string));authorized=true}return new Response(JSON.stringify(authorized?{ok:true,username:'admin',csrf_token:'fixture'}:{ok:false,error:{message:'请登录'}}),{status:authorized?200:401})});await render();await click('探索 PandaNote');await click('登录')
 await act(async()=>{for(const [name,value] of [['username','admin'],['password','fixture-only']]){const input=host.querySelector(`[name=${name}]`) as HTMLInputElement;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}))}})
 await act(async()=>{host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,10))})
 expect(writes).toEqual([{username:'admin',password:'fixture-only'}]);expect(host.textContent).toContain('private-manager-content');expect(location.hash).toBe('#workbench')
 await act(async()=>window.dispatchEvent(new Event('pandanote-auth-expired')));expect(host.textContent).not.toContain('private-manager-content');expect(host.textContent).toContain('登录已过期');expect((host.querySelector('input[type=password]') as HTMLInputElement).value).toBe('')
})
it('failed login keeps private workspace unmounted and clears password',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({ok:false,error:{message:'账号或密码错误'}}),{status:401}));await render();await click('探索 PandaNote');await click('登录');await act(async()=>{host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,10))});expect(host.textContent).toContain('账号或密码错误');expect(host.textContent).not.toContain('private-manager-content');expect((host.querySelector('input[type=password]') as HTMLInputElement).value).toBe('')
})
