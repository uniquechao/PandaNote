import {useOtaList,Badge} from './OtaCommon'
import type {Campaign} from './ota-api'
export function OtaRecent({refresh=0}:{refresh?:number}){
 const list=useOtaList<Campaign>('ota/campaigns?limit=3',refresh)
 return <div className="ota-recent">{list.error?<p className="pn-muted">{list.error}</p>:list.loading?<p role="status">正在读取升级任务…</p>:!list.items.length?<p className="pn-muted">暂无升级任务。</p>:list.items.map(c=><a key={c.campaign_id} href={'#ota/campaign/'+c.campaign_id}><strong>{c.version||'目标版本未上报'}</strong><Badge value={c.state}/><small>健康 {c.counts.SUCCEEDED||0} · 失败 {c.counts.FAILED||0} · 未知 {c.counts.UNKNOWN||0}</small></a>)}</div>
}
