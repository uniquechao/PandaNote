export type Crop={x:number;y:number;width:number;height:number}
const MAX_BYTES=10*1024*1024,MAX_PIXELS=20_000_000
function dimensions(bytes:Uint8Array,mime:string){
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength)
  if(mime==='image/png'&&bytes.length>=24&&[137,80,78,71,13,10,26,10].every((n,i)=>bytes[i]===n)&&String.fromCharCode(...bytes.subarray(12,16))==='IHDR')return {width:view.getUint32(16),height:view.getUint32(20)}
  if(mime==='image/jpeg'&&bytes[0]===255&&bytes[1]===216){
    let offset=2
    while(offset+4<=bytes.length){
      if(bytes[offset++]!==255)break
      while(bytes[offset]===255)offset++
      const marker=bytes[offset++]
      if(marker===218||marker===217)break
      if(marker===1||marker>=208&&marker<=215)continue
      const length=view.getUint16(offset)
      if(length<2||offset+length>bytes.length)break
      if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker)){
        if(length<8)break
        return {height:view.getUint16(offset+3),width:view.getUint16(offset+5)}
      }
      offset+=length
    }
  }
  throw Error('图片头无效或格式与 MIME 不符。')
}
export async function prepareImage(file:File,decode:(file:Blob)=>Promise<ImageBitmap>=createImageBitmap){
  if(file.size>MAX_BYTES)throw Error('背景超过 10 MiB。')
  if(!['image/png','image/jpeg'].includes(file.type))throw Error('只支持 PNG / JPEG。')
  const size=dimensions(new Uint8Array(await file.arrayBuffer()),file.type)
  if(size.width<=0||size.height<=0)throw Error('图片尺寸无效。')
  if(size.width*size.height>MAX_PIXELS)throw Error('背景超过 20 MP。')
  // No browser decoder runs before the bounded header check above.
  const bitmap=await decode(file)
  if(bitmap.width*bitmap.height>MAX_PIXELS){bitmap.close();throw Error('背景超过 20 MP。')}
  return bitmap
}
export function centerCrop(width:number,height:number):Crop{
  let w=width,h=Math.floor(w*800/480)
  if(h>height){h=height;w=Math.floor(h*480/800)}
  return {x:Math.floor((width-w)/2),y:Math.floor((height-h)/2),width:w,height:h}
}
export function moveCrop(crop:Crop,delta:{x:number;y:number},scale:number,width:number,height:number):Crop{
  return {...crop,x:Math.max(0,Math.min(width-crop.width,Math.round(crop.x+delta.x/scale))),y:Math.max(0,Math.min(height-crop.height,Math.round(crop.y+delta.y/scale)))}
}
// dnd-kit dispatches dragmove before updating operation.position. Include the
// pending `to`/`by` delta so a single pointer move works as well as keyboard.
export function dragDelta(position:{current:{x:number;y:number};delta:{x:number;y:number}},to?:{x:number;y:number},by?:{x:number;y:number}){
  return {x:position.delta.x+(to?to.x-position.current.x:by?.x||0),y:position.delta.y+(to?to.y-position.current.y:by?.y||0)}
}
export function cropFromMove(crop:Crop,event:{to?:{x:number;y:number};by?:{x:number;y:number}},manager:{dragOperation:{position:{current:{x:number;y:number};delta:{x:number;y:number}}}},scale:number,width:number,height:number){
  return moveCrop(crop,dragDelta(manager.dragOperation.position,event.to,event.by),scale,width,height)
}
