import {useEffect,useRef,useState} from 'react'
import {Search,Plus,RefreshCw,Monitor,ChevronDown,X,ArrowRight,Package,FileClock,Clock3} from 'lucide-react'
import {api,deviceApiPath} from './api'
import {DeviceCalendarConfig} from './DeviceCalendarConfig'
import {prepareReaderPreview} from './preview'

export type DeviceStatus = {
  version?: string|null
  settings?: {display_timezone?:string;selected_calendar_ids?:string[]}
  device?: {last_contact_at?:number|null;last_displayed_at?:number|null;last_displayed_version?:string|null}
}
const timestamp=(value:number|null|undefined)=>value?new Date(value*1000).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Singapore'}):'暂无记录'

function ReaderPreview({displayedVersion,deviceId}:{displayedVersion?:string|null;deviceId?:string}){
  const canvas=useRef<HTMLCanvasElement>(null)
  const [preview,setPreview]=useState<any>(null),[error,setError]=useState('')
  useEffect(()=>{
    let alive=true
    void api(deviceApiPath(deviceId,'/api/preview')).then(async data=>{
      const ready=await prepareReaderPreview(data)
      if(!alive)return
      canvas.current?.getContext('2d')?.drawImage(ready.frame,0,0)
      setPreview(ready.data)
    }).catch(()=>{if(alive)setError('预览暂不可用，请检查此设备配置。')})
    return()=>{alive=false}
  },[])
  return <div className="fleet-preview">
    <div className="fleet-reader"><div className="fleet-reader-screen"><canvas ref={canvas} width={480} height={800} aria-label="当前发布内容预览" hidden={!preview}/>{!preview&&<div className="fleet-preview-empty"><Monitor size={30}/><span>{error?'暂未取得预览':'正在读取预览'}</span><small>PandaNote</small></div>}</div><span className="fleet-reader-brand">PandaNote</span></div>
    <p>{preview?(preview.draft?'背景草稿 · 尚未发布':preview.version===displayedVersion?'此内容版本已有显示确认':'当前发布内容 · 等待设备确认'):error||'正在读取当前发布内容…'}</p>
    <small>管理端内容预览，不代表设备当前画面</small>
  </div>
}

function DeviceInspector({record,onClose,onChanged}:{record:DeviceRecord;onClose:()=>void;onChanged:()=>void}){
  const [tab,setTab]=useState('overview')
  const status=record.status,device=status?.device
  return <aside className="fleet-inspector" aria-label="设备详情">
    <div className="fleet-inspector-title"><div><h2>{record.name}</h2><p>{record.id} · 软件版本未上报</p></div><button className="fleet-icon-button" aria-label="关闭设备详情" onClick={onClose}><X size={19}/></button></div>
    <div className="fleet-inspector-tabs" role="tablist" aria-label="设备详情分类">{[['overview','概览'],['config','配置'],['history','升级记录']].map(([key,label])=><button key={key} role="tab" aria-selected={tab===key} aria-controls="fleet-inspector-content" id={'fleet-tab-'+key} onClick={()=>setTab(key)}>{label}</button>)}</div>
    <div id="fleet-inspector-content" role="tabpanel" aria-labelledby={'fleet-tab-'+tab}>
    {tab==='overview'?<><ReaderPreview deviceId={record.id} displayedVersion={device?.last_displayed_version}/><dl className="fleet-properties">{[['当前软件版本','未上报'],['可用软件版本','待接入'],['电量','未上报'],['已显示内容版本',device?.last_displayed_version||'尚未确认']].map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><div className="fleet-upgrade"><h3>软件升级</h3><p>软件版本与 OTA 服务待接入</p><small>接入后可查看适配版本与升级进度。</small><button className="pn-primary" disabled>升级此设备 · 待接入</button><a href="#ota">查看升级任务 <ArrowRight size={13}/></a></div></>:tab==='config'?<DeviceCalendarConfig key={record.id} deviceId={record.id} onChanged={onChanged}/>:<div className="fleet-inspector-copy"><FileClock size={28}/><h3>暂无可读取的升级记录</h3><p>当前服务尚未提供升级任务记录接口。</p><a className="pn-text-link" href="#ota">查看 OTA 升级 →</a></div>}
    </div>
  </aside>
}

export type DeviceRecord={id:string;name:string;status:DeviceStatus}
export function DeviceWorkspace({title,devices,status,loading,onRefresh}:{title:string;devices?:DeviceRecord[]|null;status?:DeviceStatus|null;loading:boolean;onRefresh:()=>void}){
 const [query,setQuery]=useState(''),[filter,setFilter]=useState('all'),[inspector,setInspector]=useState(true),[selected,setSelected]=useState(location.hash.split('/')[1]||'')
 const records:DeviceRecord[]=devices??(status?.device?[{id:'legacy',name:'当前同步终端',status}]:[])
 const known=devices!==undefined?devices!==null:!!status
 const chosen=records.find(d=>d.id===selected)||records[0]
 useEffect(()=>{const update=()=>{const id=location.hash.split('/')[1];if(id){setSelected(id);setInspector(true)}};window.addEventListener('hashchange',update);return()=>window.removeEventListener('hashchange',update)},[])
 const pending=records.filter(r=>!r.status.device?.last_displayed_at).length
 const matches=records.filter(r=>(r.name+' '+r.id).toLowerCase().includes(query.trim().toLowerCase())&&(filter==='all'||!r.status.device?.last_displayed_at))
 const open=(id:string)=>{setSelected(id);setInspector(true)}
 return <div className={'fleet-layout'+(inspector&&chosen?' has-inspector':'')}>
  <div className="fleet-main"><div className="fleet-heading"><div><h1>{title}</h1><p>管理设备、内容同步与软件升级</p></div><button className="pn-primary" disabled title="设备凭据需通过安全接入流程配置"><Plus size={17}/>添加设备</button></div>
  <div className="fleet-metrics"><div><span>全部设备</span><strong>{known?records.length:'—'}</strong></div><div><span><i className="fleet-dot"/>显示确认</span><strong>{known?records.filter(r=>r.status.device?.last_displayed_at).length:'—'}</strong></div><div><span><Clock3 size={12}/>待显示确认</span><strong>{known?pending:'—'}</strong></div><div><span>日历订阅</span><strong>{known?records.reduce((sum,r)=>sum+(r.status.settings?.selected_calendar_ids?.length||0),0):'—'}</strong></div></div>
  <div className="fleet-toolbar"><div className="fleet-filters" aria-label="设备筛选"><button className={filter==='all'?'active':''} aria-pressed={filter==='all'} onClick={()=>setFilter('all')}>全部设备</button><button className={filter==='pending'?'active':''} aria-pressed={filter==='pending'} onClick={()=>setFilter('pending')}>待显示确认 <span>{pending}</span></button></div><div className="fleet-tools"><label className="fleet-search"><Search size={15}/><input type="search" aria-label="搜索设备名称或编号" placeholder="搜索设备名称或编号" value={query} onChange={e=>setQuery(e.target.value)}/></label><button className="fleet-group" disabled title="设备分组待接入">全部分组 <ChevronDown size={14}/></button><button className="fleet-icon-button" aria-label="刷新设备状态" disabled={loading} onClick={onRefresh}><RefreshCw size={15}/></button></div></div>
  <div className="fleet-table-wrap"><table className="fleet-table"><thead><tr><th className="fleet-check"><span className="fleet-check-placeholder" aria-hidden="true"/></th><th>设备名称</th><th>状态</th><th>软件版本</th><th>最近同步</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{matches.length?matches.map(record=><tr key={record.id} className={inspector&&chosen?.id===record.id?'selected':''}><td><input type="checkbox" aria-label={'选择'+record.name} checked={inspector&&chosen?.id===record.id} onChange={e=>e.target.checked?open(record.id):setInspector(false)}/></td><td><button data-device-open className="fleet-device-name" onClick={()=>open(record.id)}><span className="fleet-device-icon"><Monitor size={19}/></span><span>{record.name}<small>{record.id}</small></span></button></td><td><span className="fleet-state"><i className="fleet-dot neutral"/>{record.status.device?.last_contact_at?'状态待确认':'尚未联系'}</span></td><td className="fleet-muted">未上报</td><td><span className="fleet-sync-time">{timestamp(record.status.device?.last_contact_at)}</span></td><td><button className="fleet-icon-button" aria-label={'查看'+record.name+'详情'} onClick={()=>open(record.id)}>···</button></td></tr>):<tr><td colSpan={6} className="fleet-table-empty">{!known?(loading?'正在读取设备状态…':'暂未取得设备状态'):query?'没有匹配的设备':records.length?'没有待显示确认的设备':'尚无已接入设备'}</td></tr>}</tbody></table></div>
  <div className="fleet-table-footer"><span>{known?'共 '+records.length+' 台设备':'等待设备记录'}</span><span>日历配置按设备独立维护</span></div><p className="fleet-data-note">历史联系不代表当前在线；运行状态与软件版本以设备上报为准。</p>
  <section className="fleet-recent"><div className="fleet-section-heading"><h2>最近升级任务</h2><a href="#ota">查看任务 <ArrowRight size={14}/></a></div><div className="fleet-task-empty"><span className="fleet-task-icon"><Package size={19}/></span><div><strong>升级任务服务待接入</strong><p>接入后显示逐台升级进度、等待唤醒与执行结果。</p></div><a href="#releases">版本发布 <ArrowRight size={14}/></a></div></section>
  </div>{inspector&&chosen&&<DeviceInspector key={chosen.id} record={chosen} onClose={()=>setInspector(false)} onChanged={onRefresh}/>}
 </div>
}
