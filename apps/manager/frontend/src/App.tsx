import {useEffect,useLayoutEffect,useRef,useState,lazy,Suspense,type ReactNode} from 'react'
import {MotionConfig,motion} from 'motion/react'
import {Group,Panel,Separator} from 'react-resizable-panels'
import {CalendarDays,ImagePlus,Monitor,RefreshCw,Link2,Save,GripVertical,Download,CheckCircle2,AlertCircle} from 'lucide-react'
import {Button} from '@/components/ui/button'
import {Input} from '@/components/ui/input'
import {Label} from '@/components/ui/label'
import {Checkbox} from '@/components/ui/checkbox'
import {Badge} from '@/components/ui/badge'
import {api as baseApi,parseResponse,request as baseRequest,deviceApiPath,appPath,isCloud} from './api'
import {CalDAVSources} from './CalDAVSources'
import {useDeviceManager as useManager} from './state'
import {ManagerScope} from './ManagerScope'
import {TimezoneSelect} from './TimezoneSelect'
import {prepareImage,centerCrop} from './image'
const CropEditor=lazy(()=>import('./CropEditor').then(module=>({default:module.CropEditor})))
import {prepareReaderPreview} from './preview'
const sourceNames:Record<string,string>={unavailable:'来源不可用',example:'模拟示例',real:'本机日历',caldav:'CalDAV 云日历',unknown:'来源未知'}
const stateNames:Record<string,string>={never_synced:'从未同步',fresh:'已读取',cached:'保留缓存',stale:'数据已过期'}
const cloudAuthNames:Record<string,string>={unavailable:'尚未配置可用日历来源，请先添加来源。',authorized:'日历连接已验证，将自动同步所选日历。',not_determined:'来源已保存，请检查连接后选择日历。',denied:'日历服务拒绝了账号或密码，已有内容会保留。',restricted:'日历服务暂不可用，已有内容会保留。'}
const authNames:Record<string,string>={unavailable:'日历桥接尚未接入；连接不会请求系统权限。',authorized:'已获授权，将自动同步所选日历，也可立即同步。',not_determined:'尚未获得权限；点击连接日历后请求。',denied:'日历访问已拒绝，现有内容会保留。',restricted:'日历访问受系统限制。'}
function stamp(value:number|null,fallback:string){return value?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):fallback}
function Heading({n,title,children}:{n:string;title:string;children?:ReactNode}){return <div className="section-heading"><span className="number">{n}</span><h2>{title}</h2>{children}</div>}
function Feedback({name}:{name:string}){const message=useManager(state=>state.messages[name]);return message?.text?<motion.p key={message.text} initial={{opacity:0,y:3}} animate={{opacity:1,y:0}} className={'result '+(message.error?'error':'')} role="status">{message.error?<AlertCircle size={14}/>:<CheckCircle2 size={14}/>}<span>{message.text}</span></motion.p>:null}
type CalendarItem={id:string;title:string;missing?:boolean;source_id?:string;source_label?:string}
export default function App({deviceId}:{deviceId?:string}){return deviceId?<ManagerScope key={deviceId}><ManagerContent deviceId={deviceId}/></ManagerScope>:<ManagerContent/>}
function ManagerContent({deviceId}:{deviceId?:string}){
  const api=(path:string,method='GET',body?:unknown)=>baseApi(deviceApiPath(deviceId,path),method,body)
  const request=(path:string,options?:RequestInit)=>baseRequest(deviceApiPath(deviceId,path),options)
  const cloud=isCloud()
  const [status,setStatus]=useState<any>(null),[readyPreview,setReadyPreview]=useState<{data:any;frame:HTMLCanvasElement}|null>(null),[calendars,setCalendars]=useState<CalendarItem[]>([]),[file,setFile]=useState<File|null>(null),[image,setImage]=useState<{width:number;height:number;url:string}|null>(null)
  const {draftZone,draftIds,setDraft,crop,setCrop,layout,setLayout,loading,run,message}=useManager(),canvas=useRef<HTMLCanvasElement>(null)
  const preview=readyPreview?.data
  async function load(initial=false){
    const data=await api('/api/status');setStatus(data)
    if(initial)setDraft(data.settings.display_timezone,data.settings.selected_calendar_ids)
    try{
      setCalendars((await api('/api/calendars')).calendars)
      message('calendar-read','')
    }catch(error){
      message('calendar-read',error instanceof Error?error.message:'日历列表读取失败。',true)
    }
    try{
      const candidate=await api('/api/preview')
      const ready=await prepareReaderPreview(candidate)
      setReadyPreview(ready)
      message('preview','')
    }catch(error){
      message('preview',error instanceof Error?error.message:'预览读取失败。',true)
    }
  }
  useEffect(()=>{void run('calendar',()=>load(true))},[])
  // Metadata and the ready frame commit together; copy before the browser paints.
  // Failed preparation never changes either the prior frame or its version links.
  useLayoutEffect(()=>{if(readyPreview&&canvas.current)canvas.current.getContext('2d')!.drawImage(readyPreview.frame,0,0)},[readyPreview])
  useEffect(()=>()=>{if(image)URL.revokeObjectURL(image.url)},[image])
  const available:CalendarItem[]=[...calendars,...draftIds.filter(id=>!calendars.some(c=>c.id===id)).map(id=>({id,title:id,missing:true}))]
  async function selectFile(selected:File|undefined){
    if(!selected)return
    setFile(null);setImage(null)
    await run('background',async()=>{const bitmap=await prepareImage(selected);const size={width:bitmap.width,height:bitmap.height};bitmap.close();setFile(selected);setCrop(centerCrop(size.width,size.height));setImage({...size,url:URL.createObjectURL(selected)});message('background','调整裁切范围后保存。')})
  }
  async function saveSettings(){
    // Server owns today/seven-days; obtain that window in the requested display
    // zone without exposing date/day controls. API independently enforces it.
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:draftZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
    await api('/api/calendar-selection','PUT',{display_timezone:draftZone,window_start:today,day_count:7,selected_calendar_ids:draftIds})
    await load();message('calendar','配置已保存，已安排自动同步；读取成功后更新日程。')
  }
  async function sync(){try{await api('/api/calendar/sync','POST',{});message('calendar','日历读取并发布成功。')}finally{await load()}}
  async function connect(){const data=await api('/api/calendar/connect','POST',{});await load();if(data.authorization!=='authorized')throw Error((cloud?'日历连接尚未通过验证：':'连接尚未获授权：')+data.authorization);message('calendar','日历已连接；可选择日历后同步。')}
  async function saveBackground(){if(!file)throw Error('请先选择背景。');const data=await parseResponse(await request('/api/background',{method:'PUT',headers:{'Content-Type':file.type,'X-Crop':JSON.stringify(crop)},body:file}));await load();message('background',data.published?'背景裁切并发布成功。':'背景草稿已保存；首次日历读取成功后发布。')}
  return <MotionConfig reducedMotion="user"><header><a className="wordmark" href={appPath('/')}>{'PandaNote'}<span>{cloud?'云管理':'本机管理'}</span></a><span className="connection">{status?sourceNames[status.provider]+(cloud?' · HTTPS':' · 仅本机'):'正在读取状态'}</span></header><main><Group id="manager-panels" orientation="horizontal" defaultLayout={layout} onLayoutChanged={setLayout} disableCursor className="manager-panels"><Panel id="config" minSize="360px" className="config-panel"><div className="intro"><span className="eyebrow">966U2 / HOME PANEL</span><h1>日程与背景</h1><p>{cloud?'配置日历来源，预览读屏内容。':'在本机配置，预览读屏内容。'}</p></div><section aria-label="日历"><Heading n="01" title="日历"><CalendarDays size={16}/><Badge variant="secondary">{status?stateNames[status.source_state]:'读取中'}</Badge></Heading>{cloud&&<CalDAVSources deviceId={deviceId} onChanged={()=>load()}/>}<p className="note">{status?.provider==='example'?'模拟示例数据 · ':''}{status&&(cloud?cloudAuthNames:authNames)[status.authorization]}</p><div className="actions"><Button disabled={!!loading} onClick={()=>run('calendar',connect)}><Link2/>连接日历</Button><Button variant="outline" disabled={!!loading} onClick={()=>run('calendar',sync)}><RefreshCw className={loading==='calendar'?'spin':''}/>立即同步</Button></div><div className="calendar-list">{[...new Set(available.map(item=>item.source_id||''))].map(group=><div className="calendar-source-group" key={group}>{group&&<h4>{available.find(item=>item.source_id===group)?.source_label||group}</h4>}{available.filter(item=>(item.source_id||'')===group).map(item=><Label key={item.id} className="calendar-choice"><Checkbox checked={draftIds.includes(item.id)} onCheckedChange={checked=>setDraft(draftZone,checked?[...draftIds,item.id]:draftIds.filter(id=>id!==item.id))}/><span>{item.title}</span>{item.missing&&<small>暂不可用 · 保留选择</small>}</Label>)}</div>)}</div><Label htmlFor="timezone" className="field">显示时区<TimezoneSelect id="timezone" value={draftZone} onChange={value=>setDraft(value,draftIds)}/></Label><p className="note">只读取显示时区本地今天起未来七天。</p><Button variant="outline" disabled={!!loading} onClick={()=>run('calendar',saveSettings)}><Save/>保存日历配置</Button><Feedback name="calendar"/><Feedback name="calendar-read"/></section><section aria-label="背景与裁切"><Heading n="02" title="背景与裁切"><ImagePlus size={16}/></Heading><p className="note">PNG / JPEG，最多 10 MiB、20 MP。解码前检查像素上限。</p><Label htmlFor="background-file" className="field">选择背景<Input id="background-file" type="file" accept="image/png,image/jpeg" disabled={!!loading} onChange={event=>void selectFile(event.target.files?.[0])}/></Label>{image&&<><Suspense fallback={<p className="note">正在载入裁切工具</p>}><CropEditor {...image}/></Suspense><div className="actions"><Button disabled={!!loading} onClick={()=>run('background',saveBackground)}><Save/>裁切并保存背景</Button><Button variant="outline" onClick={()=>setCrop(centerCrop(image.width,image.height))}>居中适配</Button></div></>}<Feedback name="background"/></section><section aria-label="设备状态"><Heading n="04" title="设备状态"><Monitor size={16}/></Heading><dl className="device">{[['连接状态',status?.device.last_contact_at?'有联系记录（不代表在线）':'尚无联系记录'],['最后联系',stamp(status?.device.last_contact_at,'无记录')],['最后显示版本',status?.device.last_displayed_version||'无记录'],['最后显示确认',stamp(status?.device.last_displayed_at,'无记录')],['上次成功读取日历',stamp(status?.last_successful_read,'从未读取')],['当前内容生成时间',stamp(status?.generated_at,'尚未发布')]].map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><p className="note">最后联系记录来自设备获取清单；显示确认由设备在校验与绘制成功后回报。</p></section></Panel><Separator className="panel-separator" aria-label="调整配置与预览宽度"><GripVertical size={16}/></Separator><Panel id="preview" minSize="320px" className="preview-panel"><div className="preview-sticky"><Heading n="03" title="读屏预览"><Button variant="ghost" size="sm" disabled={!!loading} onClick={()=>run('preview',()=>load())}><RefreshCw/>刷新</Button></Heading><div className="preview-meta"><span>{preview?sourceNames[preview.source]+' · '+(preview.draft?'草稿 / 从未同步':stateNames[preview.source_state]):'正在读取'}</span><span>480 × 800</span></div><div className="reader-frame"><canvas ref={canvas} width={480} height={800} aria-label="480 × 800 读屏内容预览"/></div><p className="note">预览使用设备内容与布局参数；浏览器与 Qt 的字体呈现可能不同。</p><p className="version">{preview?.version?'版本 '+preview.version:'尚未发布 · 背景草稿仅保存在本机'}</p><div className="downloads">{preview&&!preview.draft&&Object.entries(preview.resources as Record<string,string>).map(([name,url])=><a key={name} href={url} download={name}><Download size={12}/>{name}</a>)}</div><Feedback name="preview"/><details><summary>本版日程内容</summary><ol>{preview?.events.length?preview.events.map((event:any)=><li key={event.id}>{event.startDisplay} · {event.summary||'（无标题）'}</li>):<li>{preview?.draft?'等待首次成功读取日历':'本版日程为空'}</li>}</ol></details></div></Panel></Group></main><footer>{cloud?'PandaNote · HTTPS 云管理':'仅在 127.0.0.1 提供管理服务'}<span>PandaNote · 966U2</span></footer></MotionConfig>
}
