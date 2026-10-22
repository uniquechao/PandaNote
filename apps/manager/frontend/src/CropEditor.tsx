import {useRef} from 'react'
import {DragDropProvider,useDraggable} from '@dnd-kit/react'
import {Feedback,StyleInjector} from '@dnd-kit/dom'
import {DOMRectangle} from '@dnd-kit/dom/utilities'
import {Move} from 'lucide-react'
import {useManager} from './state'
import {moveCrop,cropFromMove,type Crop} from './image'
import {Input} from '@/components/ui/input'
import {Label} from '@/components/ui/label'
function CropHandle({scale}:{scale:number}){
  const {crop}=useManager()
  const {ref}=useDraggable({id:'background-crop'})
  return <button ref={ref} type="button" aria-label="拖动裁切范围" className="crop-handle" style={{left:crop.x*scale,top:crop.y*scale,width:crop.width*scale,height:crop.height*scale}}><Move size={20}/><span className="sr-only">空格开始拖动，方向键移动，空格确认，Escape 取消</span></button>
}
export function CropEditor({width,height,url}:{width:number;height:number;url:string}){
  const {crop,setCrop}=useManager(),start=useRef<Crop>(crop)
  const scale=Math.min(420/width,230/height)
  return <><div className="crop-stage"><DragDropProvider plugins={defaults=>[...defaults.filter(item=>(typeof item==='function'?item:item.plugin)!==Feedback&&(typeof item==='function'?item:item.plugin)!==StyleInjector),Feedback.configure({feedback:'none'}),StyleInjector.configure({nonce:document.querySelector<HTMLMetaElement>('meta[name=csp-nonce]')?.content})]} onDragStart={(_,manager)=>{start.current=useManager.getState().crop;const element=manager.dragOperation.source?.element;if(element)manager.dragOperation.shape=new DOMRectangle(element)}} onDragMove={(event,manager)=>setCrop(cropFromMove(start.current,event,manager,scale,width,height))} onDragEnd={(event,manager)=>{if(event.canceled)setCrop(start.current);else setCrop(moveCrop(start.current,manager.dragOperation.transform,scale,width,height))}}><div className="crop-original" style={{width:width*scale,height:height*scale}}><img src={url} width={width*scale} height={height*scale} alt="待裁切背景原图"/><CropHandle scale={scale}/></div></DragDropProvider></div><p className="note">原图 {width} × {height} · 拖动白框调整位置，也可聚焦白框用空格与方向键操作。</p><div className="crop-fields">{(['x','y','width','height'] as const).map((field,index)=><Label key={field} className="field" htmlFor={'crop-'+field}>{['X','Y','宽度','高度'][index]}<Input id={'crop-'+field} type="number" value={crop[field]} min={index<2?0:1} onChange={event=>setCrop({...crop,[field]:Number(event.target.value)})}/></Label>)}</div></>
}
