import {describe,it,expect,vi} from 'vitest'
import {prepareImage,moveCrop,centerCrop,dragDelta,cropFromMove} from './image'
import {parseResponse} from './api'
import {useManager} from './state'
function png(width:number,height:number){const bytes=new Uint8Array(24);bytes.set([137,80,78,71,13,10,26,10],0);bytes.set([73,72,68,82],12);const d=new DataView(bytes.buffer);d.setUint32(16,width);d.setUint32(20,height);return new File([bytes],'example.png',{type:'image/png'})}
function jpeg(width:number,height:number){return new File([new Uint8Array([255,216,255,192,0,17,8,height>>8,height&255,width>>8,width&255,3,1,17,0,2,17,0,3,17,0,255,218])],'example.jpg',{type:'image/jpeg'})}
describe('bounded predecode image flow',()=>{
  it.each([png(10000,10000),jpeg(10000,10000)])('rejects >20MP before any decoder',async file=>{const decode=vi.fn();await expect(prepareImage(file,decode)).rejects.toThrow('20 MP');expect(decode).not.toHaveBeenCalled()})
  it('rejects unsupported/corrupt headers before decoding',async()=>{const decode=vi.fn();await expect(prepareImage(new File(['invalid'],'x.png',{type:'image/png'}),decode)).rejects.toThrow();expect(decode).not.toHaveBeenCalled()})
  it('accepts bounded JPEG and returns oriented dimensions',async()=>{const decode=vi.fn(async()=>({width:1000,height:600}) as ImageBitmap);const data=await prepareImage(jpeg(600,1000),decode);expect(data.width).toBe(1000);expect(data.height).toBe(600)})
})
describe('crop coordinates',()=>{
  it('reads live manager position when installed dnd snapshots omit position getters',()=>{const event={operation:{position:{}},to:{x:715,y:300}};const manager={dragOperation:{position:{current:{x:680,y:277},delta:{x:0,y:0}}}};expect(cropFromMove({x:150,y:0,width:480,height:800},event,manager,.23,900,1000)).toEqual({x:302,y:100,width:480,height:800})})
  it('uses pending dnd move coordinates rather than the previous operation transform',()=>{expect(dragDelta({current:{x:680,y:277},delta:{x:0,y:0}},{x:715,y:300})).toEqual({x:35,y:23})})
  it('centers a portrait rectangle inside the source',()=>{expect(centerCrop(900,1000)).toEqual({x:150,y:0,width:600,height:1000})})
  it('converts CSS drag delta to oriented pixels and clamps to image bounds',()=>{expect(moveCrop({x:150,y:0,width:480,height:800},{x:60,y:20},.2,900,1000)).toEqual({x:420,y:100,width:480,height:800})})
})
describe('response/state failure retention',()=>{
  it('handles non-JSON server errors without exposing a JSON parser exception',async()=>{await expect(parseResponse(new Response('Internal Server Error',{status:500}))).rejects.toThrow('HTTP 500')})
  it('surfaces structured SQLite detail',async()=>{await expect(parseResponse(new Response(JSON.stringify({ok:false,error:{message:'本地存储失败：database is locked'}}),{status:500}))).rejects.toThrow('database is locked')})
  it('keeps draft/layout after a failed operation and resets loading',async()=>{const s=useManager.getState();s.setDraft('Asia/Singapore',['work']);s.setLayout({config:60,preview:40});await s.run('save',async()=>{throw Error('database is locked')});const next=useManager.getState();expect(next.loading).toBe(null);expect(next.messages.save).toEqual({text:'database is locked',error:true});expect(next.draftIds).toEqual(['work']);expect(next.layout).toEqual({config:60,preview:40})})
})
