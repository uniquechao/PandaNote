// Content and geometry from one immutable API preview; no independent current lookups.
function fitText(ctx:CanvasRenderingContext2D,text:string,x:number,y:number,width:number){let value=text;if(ctx.measureText(value).width>width){while(value&&ctx.measureText(value+'…').width>width)value=value.slice(0,-1);value+='…';}ctx.fillText(value,x,y);}
function titleLines(ctx:CanvasRenderingContext2D,text:string,x:number,y:number,width:number){let rest=text.trim().replace(/\s+/g,' ')||'（无标题）',first='';for(const char of rest){if(ctx.measureText(first+char).width>width)break;first+=char;}ctx.fillText(first,x,y);if(first.length<rest.length)fitText(ctx,rest.slice(first.length),x,y+31,width);}
export async function drawReader(c:HTMLCanvasElement,data:any,cancelled:()=>boolean){
  const bg=await fetch(data.draft?data.resources.background:data.resources['background.png']);if(!bg.ok)throw new Error('预览背景读取失败。');const image=await createImageBitmap(await bg.blob());
  if(cancelled()){image.close();return;}
  const ctx=c.getContext('2d')!;ctx.drawImage(image,0,0,480,800);ctx.fillStyle='white';ctx.fillRect(...(data.layout.white_top as [number,number,number,number]));ctx.fillRect(...(data.layout.white_bottom as [number,number,number,number]));
  const home=data.home,date=home?.date;ctx.fillStyle='#000';ctx.font='bold 30px sans-serif';const day=date?new Date(date+'T12:00:00Z'):null;
  ctx.fillText(day?`${day.getUTCFullYear()}年${day.getUTCMonth()+1}月${day.getUTCDate()}日`:'日程与背景',28,65);
  ctx.font='21px sans-serif';ctx.fillText(day?(!home.trusted_time?'缓存日期 · ':'')+['星期日','星期一','星期二','星期三','星期四','星期五','星期六'][day.getUTCDay()]:'等待日历同步',28,106);
  ctx.strokeStyle='#919191';ctx.beginPath();ctx.moveTo(28,128);ctx.lineTo(452,128);ctx.stroke();
  const events=home?.events||[],rowHeight=events.length<3?data.layout.row_heights.fewer_than_three:data.layout.row_heights.three;
  if(!events.length){ctx.font='26px sans-serif';ctx.fillText(data.draft?'尚未同步日历':home.trusted_time?'今天暂无日程':'缓存中暂无日程',28,234);}
  events.forEach((event:any,index:number)=>{const y=146+index*rowHeight;ctx.save();ctx.beginPath();ctx.rect(28,y,424,rowHeight-4);ctx.clip();ctx.fillStyle='black';ctx.font='18px sans-serif';const when=(event.startDate!==date?event.startDate.slice(5)+'  ':'')+(event.allDay?'全天':event.startDisplay);fitText(ctx,when,28,y+19,424);ctx.font='bold 24px sans-serif';titleLines(ctx,event.summary,28,y+51,424);if(event.location&&rowHeight-4>=122){ctx.font='17px sans-serif';ctx.fillStyle='#464646';fitText(ctx,event.location,28,y+109,424);}ctx.restore();});
  ctx.fillStyle='white';ctx.fillRect(...(data.layout.white_bottom as [number,number,number,number]));ctx.fillStyle='black';ctx.font='15px sans-serif';ctx.textAlign='center';const generated=data.generated_at?new Date(data.generated_at*1000).toISOString().slice(5,16).replace('T',' '):'';fitText(ctx,data.draft?'尚未同步日历':`${home.sync_failed?'日历数据已过期':home.trusted_time?'日历已同步':'缓存时间'} · 上次同步 ${generated} UTC`,240,694,448);ctx.strokeStyle='black';ctx.lineWidth=2;ctx.strokeRect(161,705,158,62);ctx.font='23px sans-serif';ctx.fillText('应用',240,745);ctx.textAlign='left';image.close();
}


export async function prepareReaderPreview(data:any){
  const frame=document.createElement('canvas')
  frame.width=480;frame.height=800
  await drawReader(frame,data,()=>false)
  return {data,frame}
}
