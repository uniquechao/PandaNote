// @vitest-environment jsdom
import {act} from 'react'
import {createRoot,type Root} from 'react-dom/client'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {DeviceCalendarConfig} from './DeviceCalendarConfig'
import Workspace from './Workspace'
import {deviceApiPath} from './api'
let host:HTMLDivElement,root:Root
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);history.replaceState(null,'','/');document.head.innerHTML='';host=document.createElement('div');document.body.append(host);root=createRoot(host)})
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals()})
it('switches calendar owners and saves only the selected device settings',async()=>{
 const writes:{path:string;body:any}[]=[]
 vi.stubGlobal('fetch',async(path:string,options:RequestInit={})=>{const id=path.includes('/device_b/')?'b':'a';let data:any={ok:true};if(options.method==='PUT')writes.push({path,body:JSON.parse(options.body as string)});if(path.endsWith('/status'))data={ok:true,settings:{display_timezone:'Asia/Singapore',selected_calendar_ids:[id+'-calendar']}};if(path.endsWith('/calendars'))data={ok:true,calendars:[{id:id+'-calendar',title:id==='a'?'Alice 的日历':'Bob 的日历'}]};if(path.endsWith('/caldav/sources'))data={ok:true,sources:[]};return new Response(JSON.stringify(data))})
 await act(async()=>{root.render(<DeviceCalendarConfig key="a" deviceId="device_a" onChanged={()=>{}}/>);await new Promise(r=>setTimeout(r,10))});expect(host.textContent).toContain('Alice 的日历')
 await act(async()=>{root.render(<DeviceCalendarConfig key="b" deviceId="device_b" onChanged={()=>{}}/>);await new Promise(r=>setTimeout(r,10))});expect(host.textContent).not.toContain('Alice 的日历');expect(host.textContent).toContain('Bob 的日历')
 await act(async()=>{[...host.querySelectorAll('button')].find(b=>b.textContent?.includes('保存此设备订阅'))!.click();await new Promise(r=>setTimeout(r,10))})
 expect(writes).toHaveLength(1);expect(writes[0].path).toBe('/api/devices/device_b/calendar-selection');expect(writes[0].body.selected_calendar_ids).toEqual(['b-calendar'])
})
it('keeps global calendar maintenance out of the reference navigation',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({ok:true,devices:[]})))
 await act(async()=>{root.render(<Workspace/>);await new Promise(r=>setTimeout(r,10))})
 const labels=[...host.querySelectorAll('nav[aria-label="管理导航"] a')].map(a=>a.textContent)
 expect(labels).toEqual(['工作台','设备管理','内容管理','版本发布','升级任务','设置']);expect(host.querySelector('.caldav-sources')).toBeNull()
})
it('rejects device identifiers that could escape a scoped path',()=>{expect(deviceApiPath('device_a','/api/status')).toBe('/api/devices/device_a/status');expect(()=>deviceApiPath('../device_b','/api/status')).toThrow();expect(()=>deviceApiPath('device_a','/reader/manifest')).toThrow()})
