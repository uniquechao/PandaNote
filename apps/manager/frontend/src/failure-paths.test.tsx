// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act} from 'react'
import {createRoot,type Root} from 'react-dom/client'
import App from './App'
import {useManager} from './state'

let root:Root,host:HTMLDivElement,version='A',listFails=false,resourceFails=false,decodeFails=false
const calendar={id:'work',title:'保留的工作日历'}
function response(data:unknown,status=200){return new Response(JSON.stringify(data),{status})}
function preview(){return {schema:1,ok:true,version,draft:false,source:'example',source_state:'fresh',generated_at:1792515600,events:[],home:{date:'2026-10-21',trusted_time:true,events:[],sync_failed:false},layout:{white_top:[0,0,480,458],white_bottom:[0,680,480,120],row_heights:{fewer_than_three:140,three:98}},resources:{'background.png':`/api/resources/${version}/background.png`,'content.ini':`/api/resources/${version}/content.ini`}}}
function frame(canvas:HTMLCanvasElement){return (canvas as HTMLCanvasElement&{frame?:string}).frame}
async function click(text:string){const button=[...host.querySelectorAll('button')].find(el=>el.textContent?.includes(text));expect(button).toBeDefined();await act(async()=>{button!.click();await new Promise(resolve=>setTimeout(resolve,20))})}
beforeEach(async()=>{
  version='A';listFails=false;resourceFails=false;decodeFails=false
  useManager.setState({draftIds:[],draftZone:'',messages:{},loading:null,layout:{config:54,preview:46}})
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}})
  vi.stubGlobal('fetch',vi.fn(async(input:string)=>{
    if(input==='/api/status')return response({schema:1,ok:true,authorization:'authorized',provider:'example',source_state:'fresh',settings:{display_timezone:'Asia/Singapore',selected_calendar_ids:['work']},device:{},generated_at:null,last_successful_read:null})
    if(input==='/api/calendars')return listFails?response({ok:false,error:{message:'示例日历枚举失败：桥接断开'}},409):response({ok:true,calendars:[calendar]})
    if(input==='/api/preview')return response(preview())
    if(input==='/api/calendar-selection')return response({ok:true,saved:true})
    if(input.startsWith('/api/resources/'))return new Response(input,{status:resourceFails&&input.includes('/B/')?500:200})
    throw Error('unexpected request '+input)
  }))
  vi.stubGlobal('createImageBitmap',vi.fn(async(blob:Blob)=>{const url=await blob.text();if(decodeFails&&url.includes('/B/'))throw Error('示例图片解码失败');return {version:url.split('/')[3],close(){}}}))
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockImplementation(function(this:HTMLCanvasElement){const canvas=this;return {drawImage(source:{version?:string;frame?:string}){(canvas as HTMLCanvasElement&{frame?:string}).frame=source.version||source.frame},fillRect(){},fillText(){},measureText(){return {width:0}},beginPath(){},moveTo(){},lineTo(){},stroke(){},strokeRect(){},save(){},restore(){},rect(){},clip(){}} as unknown as CanvasRenderingContext2D})
  host=document.createElement('div');document.body.append(host);root=createRoot(host)
  await act(async()=>{root.render(<App/>);await new Promise(resolve=>setTimeout(resolve,20))})
})
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals()})
it.each(['fetch','decode'])('keeps rendered A/version/download together when second preview B %s fails',async failure=>{
  expect(host.querySelector('.version')?.textContent).toBe('版本 A')
  expect(frame(host.querySelector('canvas')!)).toBe('A')
  version='B';resourceFails=failure==='fetch';decodeFails=failure==='decode'
  await click('刷新')
  expect(frame(host.querySelector('canvas')!)).toBe('A')
  expect(host.querySelector('.version')?.textContent).toBe('版本 A')
  expect(host.querySelector('.downloads a')?.getAttribute('href')).toContain('/A/')
  expect(host.textContent).toContain(failure==='fetch'?'预览背景读取失败':'示例图片解码失败')
})
it('keeps successful calendar titles and the concrete list error alongside mutation success with authorized status',async()=>{
  expect(host.textContent).toContain('保留的工作日历')
  listFails=true
  await click('保存日历配置')
  expect(host.textContent).toContain('已获授权')
  expect(host.textContent).toContain('配置已保存')
  expect(host.textContent).toContain('示例日历枚举失败：桥接断开')
  expect(host.textContent).toContain('保留的工作日历')
  expect(host.textContent).not.toContain('暂不可用 · 保留选择')
})
