const common:Record<string,string>={'Asia/Shanghai':'中国标准时间 · 上海','Asia/Singapore':'新加坡','Asia/Hong_Kong':'香港','Asia/Tokyo':'东京','Asia/Seoul':'首尔','Europe/London':'伦敦','Europe/Paris':'巴黎','America/New_York':'纽约','America/Los_Angeles':'洛杉矶','Australia/Sydney':'悉尼','UTC':'协调世界时'}
const supported=typeof Intl.supportedValuesOf==='function'?Intl.supportedValuesOf('timeZone'):[]
export function TimezoneSelect({value,onChange,disabled,id,label}:{value:string;onChange:(value:string)=>void;disabled?:boolean;id?:string;label?:string}){
 const values=[...new Set([value,...Object.keys(common),...supported])].filter(Boolean)
 return <select className="pn-timezone-select" id={id} value={value} disabled={disabled} aria-label={label} onChange={e=>onChange(e.target.value)}>{!value&&<option value="">选择显示时区</option>}{values.map(zone=><option key={zone} value={zone}>{common[zone]?common[zone]+' · ':''}{zone}</option>)}</select>
}
