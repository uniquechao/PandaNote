let csrfToken=''
export function setCsrfToken(value:string){csrfToken=value}
export function isCloud(){return typeof document!=='undefined'&&document.querySelector('meta[name="cloud-profile"]')?.getAttribute('content')==='true'}
export function appPrefix(){const value=typeof document==='undefined'?'':document.querySelector('meta[name="app-prefix"]')?.getAttribute('content')||'';if(value!==''&&value!=='/pandanote')throw Error('管理页面路径无效。');return value}
export function appPath(path:string){const prefix=appPrefix();if(!path.startsWith('/')||path.startsWith('//')||path.includes('\\')||path.includes('..'))throw Error('管理请求路径无效。');return prefix&&path.startsWith(prefix+'/')?path:prefix+path}
export async function parseResponse(response:Response){
  const text=await response.text()
  let data
  try{data=JSON.parse(text)}catch{throw Error(`管理服务响应无效（HTTP ${response.status}）；已有内容会保留。`)}
  if(!response.ok||!data?.ok)throw Error(data?.error?.message||`操作失败（HTTP ${response.status}）`)
  return data
}
export async function request(path:string,options:RequestInit={}){
 const method=options.method||'GET',headers=new Headers(options.headers)
 if(!['GET','HEAD'].includes(method)&&csrfToken)headers.set('X-CSRF-Token',csrfToken)
 const response=await fetch(appPath(path),{...options,headers,credentials:'same-origin'})
 if(response.status===401&&isCloud()&&!path.endsWith('/auth/login')&&!path.endsWith('/auth/session')){setCsrfToken('');window.dispatchEvent(new Event('pandanote-auth-expired'))}
 return response
}
export async function api(path:string,method='GET',body?:unknown){
 return parseResponse(await request(path,{method,headers:body!==undefined?{'Content-Type':'application/json'}:{},body:body===undefined?undefined:JSON.stringify(body)}))
}
// Bind every configuration request to the selected, authenticated device ID.
export function deviceApiPath(deviceId:string|undefined,path:string){
 if(!deviceId)return path
 if(!/^[A-Za-z0-9_-]{1,64}$/.test(deviceId)||!path.startsWith('/api/'))throw Error('设备配置路径无效。')
 return '/api/devices/'+deviceId+path.slice(4)
}
