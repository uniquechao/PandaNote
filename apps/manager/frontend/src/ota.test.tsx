// @vitest-environment jsdom
import {act} from 'react'
import {createRoot,type Root} from 'react-dom/client'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {OtaReleases} from './OtaReleases'
import {OtaCampaigns} from './OtaCampaigns'
import {OtaDevicePanel} from './OtaDevice'
import {setCsrfToken} from './api'
let host:HTMLDivElement,root:Root,calls:{path:string;options:RequestInit}[]
const release={release_id:'a'.repeat(32),input_sha256:'b'.repeat(64),version:'2.0',model:'966U2',channel:'stable',sequence:2,state:'APPROVED',revision:3}
const reply=(data:Record<string,unknown>,status=200)=>new Response(JSON.stringify({schema:1,ok:true,...data}),{status})
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);calls=[];setCsrfToken('fixture-csrf')})
afterEach(async()=>{await act(async()=>root.unmount());host.remove();setCsrfToken('');vi.unstubAllGlobals()})
const render=async(node:React.ReactNode)=>act(async()=>{root.render(node);await new Promise(r=>setTimeout(r,10))})
const click=async(text:string)=>act(async()=>{const button=Array.from(host.querySelectorAll('button')).find(b=>b.textContent===text);expect(button).toBeDefined();button!.click();await new Promise(r=>setTimeout(r,10))})
const select=async(index:number,value:string)=>act(async()=>{const field=host.querySelectorAll('select')[index];Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('change',{bubbles:true}));await new Promise(r=>setTimeout(r,10))})
it('shows releases and confirms revision-bound revocation with idempotency and CSRF',async()=>{
 vi.stubGlobal('fetch',async(path:string,options:RequestInit={})=>{calls.push({path,options});if(options.method==='POST')return reply({release_id:release.release_id});return reply({items:path.includes('/inputs')?[]:[release],next_cursor:null})})
 await render(<OtaReleases/>);expect(host.textContent).toContain('2.0');await click('查看详情');await click('撤回发布');expect(host.textContent).toContain('离线设备已取得的有效授权仍可能执行')
 await act(async()=>{const field=host.querySelector('textarea')!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,'测试撤回');field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}))});await click('确认操作')
 const call=calls.find(c=>c.options.method==='POST')!;expect(call.path).toContain('/revoke');expect(JSON.parse(call.options.body as string)).toEqual({revision:3,reason:'测试撤回'});const headers=new Headers(call.options.headers);expect(headers.get('idempotency-key')).toMatch(/^[a-f0-9]{32}$/);expect(headers.get('x-csrf-token')).toBe('fixture-csrf')
})
it('previews exact pilot and remaining devices before creating a draft',async()=>{
 vi.stubGlobal('fetch',async(path:string,options:RequestInit={})=>{calls.push({path,options});if(path.includes('/devices/'))return reply({enrolled:true,model:'966U2',channels:['stable']});if(path.includes('/releases'))return reply({items:[release],next_cursor:null});if(options.method==='POST')return reply({campaign_id:'c'.repeat(32)});if(path.endsWith('/'+'c'.repeat(32)))return reply({campaign:{campaign_id:'c'.repeat(32),state:'DRAFT',revision:1,batch:0,policy:{observation_seconds:86400},targets:[]}});return reply({items:[],next_cursor:null})})
 await render(<OtaCampaigns devices={[{id:'one',name:'设备一',status:{}},{id:'two',name:'设备二',status:{}}]}/>);await click('创建灰度任务');await select(0,release.release_id)
 await act(async()=>{host.querySelectorAll<HTMLInputElement>('input[type=checkbox]').forEach(c=>c.click())});await select(1,'one');await click('预览并创建任务');expect(calls.filter(c=>c.options.method==='POST')).toHaveLength(0);expect(host.textContent).toContain('第一批：one；第二批：two');await click('确认创建草稿')
 expect(JSON.parse(calls.find(c=>c.options.method==='POST')!.options.body as string)).toMatchObject({device_ids:['one','two'],batches:[['one'],['two']]})
})
it('keeps health reports, recovery and content status distinct',async()=>{
 vi.stubGlobal('fetch',async(path:string)=>path.endsWith('/attempts')?reply({attempts:[{attempt_id:'d'.repeat(32),sequence:2,state:'RECOVERY_REQUIRED',recovery:{candidate_sha256:'e'.repeat(64)}}],events:[],next_cursor:null}):reply({enrolled:true,confirmed:{native_sha256:'f'.repeat(64),boot_id:'a'.repeat(24)},observed:{state:'WAITING_SAFE_WINDOW'},last_report:1792516000,automatic_install:null}))
 await render(<OtaDevicePanel deviceId="one" history/>);expect(host.textContent).toContain('等待本地安全窗口');expect(host.textContent).toContain('需要受控恢复');expect(host.textContent).toContain('本地自动安装未上报');expect(host.textContent).not.toContain('100%');expect(host.textContent).toContain('恢复材料引用')
})
it('shows disabled service errors without pretending success',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({schema:1,ok:false,error:{code:'ota_disabled',message:'OTA 尚未启用'}}),{status:503}));await render(<OtaReleases/>);expect(host.querySelector('[role=alert]')?.textContent).toContain('OTA 尚未启用');expect(host.textContent).not.toContain('已批准')
})

it('shows actionable blocking reasons and keeps known data after refresh failure',async()=>{
 let failed=false
 vi.stubGlobal('fetch',async()=>{if(failed)throw new Error('网络已断开');return reply({enrolled:true,confirmed:{version:'1.0',native_sha256:'f'.repeat(64)},observed:{state:'WAITING_SAFE_WINDOW',error_code:'power_unsafe',reported_at:1792516000},last_report:1792516000,last_event:{event:{state:'OFFERED'},received_at:1792516001}})})
 await render(<OtaDevicePanel deviceId="one"/>);expect(host.textContent).toContain('保持安全供电');expect(host.textContent).toContain('有效报告时间');expect(host.textContent).toContain('最后收到的原始事件')
 failed=true;await click('刷新升级状态');expect(host.textContent).toContain('1.0');expect(host.textContent).toContain('显示上次已知数据')
})
it('opens a direct campaign link with server observation constraints and collapsed creation',async()=>{
 const id='c'.repeat(32);location.hash='ota/campaign/'+id
 const campaign={campaign_id:id,version:'2.0',release_id:release.release_id,state:'RUNNING',revision:2,batch:0,policy:{observation_seconds:86400},counts:{SUCCEEDED:1},progress:{healthy:1,total:1,ready_at:1999999999,can_advance:false,reason:'observation_pending'},targets:[]}
 vi.stubGlobal('fetch',async(path:string)=>path.endsWith('/'+id)?reply({campaign}):reply({items:path.includes('releases')?[release]:[campaign],next_cursor:null}))
 await render(<OtaCampaigns devices={[]}/>);expect(host.querySelector('select')).toBeNull();expect(host.textContent).toContain('目标软件：2.0');expect(host.textContent).toContain('观察期尚未结束')
 const advance=Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='推进批次')!;expect(advance.disabled).toBe(true)
 location.hash=''
})
it('refreshes active monitoring on a bounded timer and stops after unmount',async()=>{
 vi.useFakeTimers();const campaign={campaign_id:'c'.repeat(32),version:'2.0',state:'RUNNING',batch:0,counts:{},policy:{observation_seconds:86400}}
 let requests=0;vi.stubGlobal('fetch',async(path:string)=>{requests++;return reply({items:path.includes('releases')?[release]:[campaign],next_cursor:null})})
 try{
  await act(async()=>{root.render(<OtaCampaigns devices={[]}/>);await vi.advanceTimersByTimeAsync(10)})
  const initial=requests;await act(async()=>{await vi.advanceTimersByTimeAsync(14900)});expect(requests).toBe(initial)
  await act(async()=>{await vi.advanceTimersByTimeAsync(200)});expect(requests).toBeGreaterThan(initial)
  await act(async()=>{root.render(<div/>)});const stopped=requests;await act(async()=>{await vi.advanceTimersByTimeAsync(30000)});expect(requests).toBe(stopped)
 }finally{vi.useRealTimers()}
})
