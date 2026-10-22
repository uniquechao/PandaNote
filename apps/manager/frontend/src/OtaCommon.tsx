import {useEffect,useState} from 'react'
import {otaGet,label} from './ota-api'
export function Badge({value}:{value:string|null|undefined}){return <span className={'ota-badge ota-'+(value||'unknown').toLowerCase()}>{label(value)}</span>}
export function useOtaList<T>(path:string,refresh:number){
 const [items,setItems]=useState<T[]>([]),[cursor,setCursor]=useState<string|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true)
 useEffect(()=>{let alive=true;setItems([]);setCursor(null);setLoading(true);void otaGet(path).then(data=>{if(alive){setItems(data.items);setCursor(data.next_cursor);setError('')}}).catch(e=>{if(alive)setError(e.message)}).finally(()=>{if(alive)setLoading(false)});return()=>{alive=false}},[path,refresh])
 async function more(){if(!cursor)return;setLoading(true);try{const data=await otaGet(path+(path.includes('?')?'&':'?')+'cursor='+encodeURIComponent(cursor));setItems(old=>[...old,...data.items]);setCursor(data.next_cursor);setError('')}catch(e){setError(e instanceof Error?e.message:'读取失败。')}finally{setLoading(false)}}
 return {items,cursor,error,loading,more}
}
export function OtaNotice(){return <p className="ota-notice">暂停停止新增授权与续期；撤回或取消还会停止后续下载。离线设备已取得的有效授权仍可能执行，结果需等待设备确认。</p>}
export function Feedback({error,loading}:{error:string;loading?:boolean}){return <>{error&&<p className="pn-warning" role="alert">{error}</p>}{loading&&<p role="status" className="pn-muted">正在读取 OTA 数据…</p>}</>}
