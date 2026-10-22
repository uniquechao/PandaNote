import {useEffect,useState} from 'react'
import {CalendarDays,RefreshCw,Link2,Save,ArrowRight} from 'lucide-react'
import {api,deviceApiPath} from './api'
import {CalDAVSources} from './CalDAVSources'
import {TimezoneSelect} from './TimezoneSelect'
export function DeviceCalendarConfig({deviceId,onChanged}:{deviceId:string;onChanged:()=>void}){
 const [calendars,setCalendars]=useState<any[]>([]),[ids,setIds]=useState<string[]>([]),[zone,setZone]=useState(''),[ready,setReady]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('')
 const scoped=(path:string,method='GET',body?:unknown)=>api(deviceApiPath(deviceId,path),method,body)
 async function load(initial=false){
  const status=await scoped('/api/status')
  if(initial){setZone(status.settings.display_timezone);setIds(status.settings.selected_calendar_ids);setReady(true)}
  try{setCalendars((await scoped('/api/calendars')).calendars)}catch{setCalendars([]);setMessage('来源连接成功后可选择日历；已保存的选择会保留。')}
 }
 useEffect(()=>{let alive=true;setReady(false);setIds([]);setZone('');setCalendars([]);setError('');
  void scoped('/api/status').then(async status=>{if(!alive)return;setZone(status.settings.display_timezone);setIds(status.settings.selected_calendar_ids);setReady(true);try{const data=await scoped('/api/calendars');if(alive)setCalendars(data.calendars)}catch{if(alive)setMessage('请先添加来源并检查连接。')}}).catch(()=>{if(alive)setError('此设备日历配置读取失败，请重新打开配置。')});return()=>{alive=false}
 },[deviceId])
 async function run(action:()=>Promise<unknown>,success:string){setBusy(true);setError('');setMessage('');try{await action();await load();onChanged();setMessage(success)}catch(e){setError(e instanceof Error?e.message:'操作失败。')}finally{setBusy(false)}}
 async function save(){const today=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());await scoped('/api/calendar-selection','PUT',{display_timezone:zone,window_start:today,day_count:7,selected_calendar_ids:ids})}
 const available=[...calendars,...ids.filter(id=>!calendars.some(c=>c.id===id)).map(id=>({id,title:'已保存日历（暂不可用）'}))]
 return <div className="device-calendar-config"><div className="device-config-heading"><CalendarDays size={18}/><h3>日历订阅</h3></div><CalDAVSources key={deviceId} deviceId={deviceId} onChanged={async()=>{await load();onChanged()}}/>
 <div className="device-calendar-actions"><button className="pn-secondary" disabled={busy||!ready} onClick={()=>void run(async()=>{const result=await scoped('/api/calendar/connect','POST',{});if(result.authorization!=='authorized')throw Error('连接尚未通过验证，请检查此设备的日历账号。')},'此设备日历连接已通过验证。')}><Link2 size={14}/>检查连接</button><button className="pn-secondary" disabled={busy||!ready} onClick={()=>void run(()=>scoped('/api/calendar/sync','POST',{}),'此设备日历已同步。')}><RefreshCw size={14}/>立即同步</button></div>
 <div className="device-calendar-choices"><h4>显示的日历</h4>{available.length?available.map(calendar=><label key={calendar.id}><input type="checkbox" checked={ids.includes(calendar.id)} disabled={busy||!ready} onChange={e=>setIds(e.target.checked?[...ids,calendar.id]:ids.filter(id=>id!==calendar.id))}/><span>{calendar.source_label&&<small>{calendar.source_label} · </small>}{calendar.title}</span></label>):<p className="device-config-note">尚无可选择的日历。</p>}</div>
 <label className="device-timezone">显示时区<TimezoneSelect value={zone} disabled={busy||!ready} onChange={setZone} label="此设备显示时区"/></label><button className="pn-primary device-save-calendar" disabled={busy||!ready} onClick={()=>void run(save,'此设备的订阅配置已保存。')}><Save size={14}/>保存此设备订阅</button>{message&&<p role="status" className="device-config-message">{message}</p>}{error&&<p role="alert" className="device-config-error">{error}</p>}<a className="device-config-editor" href={'#device-config/'+deviceId}>编辑此设备背景与内容 <ArrowRight size={14}/></a></div>
}
