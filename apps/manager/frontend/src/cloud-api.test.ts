// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest'
import {api,setCsrfToken} from './api'
afterEach(()=>{document.head.innerHTML='';vi.unstubAllGlobals();setCsrfToken('')})
it('routes API operations below the injected prefix and sends CSRF only on mutation',async()=>{
 document.head.innerHTML='<meta name="app-prefix" content="/pandanote"><meta name="cloud-profile" content="true">'
 const calls:{path:string,options:RequestInit}[]=[]
 vi.stubGlobal('fetch',async(path:string,options:RequestInit)=>{calls.push({path,options});return new Response('{"ok":true}')})
 setCsrfToken('fixture-csrf');await api('/api/caldav/sources','POST',{label:'work',url:'https://calendar.example',username:'u',password:'fixture-only'});await api('/api/status')
 expect(calls[0].path).toBe('/pandanote/api/caldav/sources');expect(calls[0].options.credentials).toBe('same-origin');expect(new Headers(calls[0].options.headers).get('x-csrf-token')).toBe('fixture-csrf')
 expect(new Headers(calls[1].options.headers).has('x-csrf-token')).toBe(false)
})
it('keeps local loopback paths and refuses unexpected prefixes or off-origin API URLs',async()=>{
 const paths:string[]=[];vi.stubGlobal('fetch',async(path:string)=>{paths.push(path);return new Response('{"ok":true}')})
 await api('/api/status');expect(paths).toEqual(['/api/status'])
 document.head.innerHTML='<meta name="app-prefix" content="https://evil.invalid">';await expect(api('/api/status')).rejects.toThrow()
 document.head.innerHTML='<meta name="app-prefix" content="/pandanote">';await expect(api('https://evil.invalid/api/status')).rejects.toThrow();expect(paths.length).toBe(1)
})
