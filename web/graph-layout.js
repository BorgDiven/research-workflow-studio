/* Pack complete graph components without resizing or splitting their branches. */
(function(root){
  'use strict';
  function topologyPlan(nodes,edges,width,height,gapX,gapY,availableWidth=width,direction='horizontal'){
    if(!nodes.length)return {width:0,height:0,positions:[]};
    const byId=new Map(nodes.map(n=>[n.id,n])),parents=new Map(nodes.map(n=>[n.id,[]])),children=new Map(nodes.map(n=>[n.id,[]]));
    edges.forEach(([a,b])=>{if(byId.has(a)&&byId.has(b)){parents.get(b).push(a);children.get(a).push(b);}});
    const ranks=new Map(),visiting=new Set();
    const rank=id=>{if(ranks.has(id))return ranks.get(id);if(visiting.has(id))throw new Error('Research graph contains a cycle');visiting.add(id);const r=parents.get(id).length?1+Math.max(...parents.get(id).map(rank)):0;visiting.delete(id);ranks.set(id,r);return r;};
    [...byId.keys()].sort().forEach(rank);
    const seen=new Set(),components=[];
    [...byId.keys()].sort().forEach(id=>{if(seen.has(id))return;const ids=[],stack=[id];while(stack.length){const next=stack.pop();if(seen.has(next))continue;seen.add(next);ids.push(next);stack.push(...parents.get(next),...children.get(next));}components.push(ids.sort());});
    components.sort((a,b)=>b.length-a.length||a[0].localeCompare(b[0]));
    const plans=components.map(ids=>{
      const layers=new Map();ids.forEach(id=>{const r=ranks.get(id);if(!layers.has(r))layers.set(r,[]);layers.get(r).push(id);});
      const order=new Map();
      [...layers.keys()].sort((a,b)=>a-b).forEach(r=>{const layer=layers.get(r);layer.sort((a,b)=>{const center=id=>parents.get(id).length?parents.get(id).reduce((sum,p)=>sum+(order.get(p)||0),0)/parents.get(id).length:0;return center(a)-center(b)||a.localeCompare(b);});layer.forEach((id,i)=>order.set(id,i));});
      const rows=Math.max(...[...layers.values()].map(a=>a.length)),depth=Math.max(...layers.keys()),vertical=direction==='vertical',h=vertical?(depth+1)*height+depth*gapY:rows*height+(rows-1)*gapY,w=vertical?rows*width+(rows-1)*gapX:(depth+1)*width+depth*gapX,positions=[];
      layers.forEach((layer,r)=>{const layerSize=layer.length*(vertical?width:height)+(layer.length-1)*(vertical?gapX:gapY);layer.forEach((id,i)=>positions.push({id,rank:r,x:vertical?(w-layerSize)/2+i*(width+gapX):r*(width+gapX),y:vertical?r*(height+gapY):(h-layerSize)/2+i*(height+gapY),component:ids[0]}));});
      return {width:w,height:h,positions};
    });
    const limit=Math.max(width,Number.isFinite(availableWidth)?availableWidth:width,...plans.map(p=>p.width)),positions=[];let x=0,y=0,rowHeight=0,usedWidth=0;
    plans.forEach(plan=>{if(x&&x+plan.width>limit+.1){x=0;y+=rowHeight+gapY;rowHeight=0;}plan.positions.forEach(p=>positions.push({...p,x:p.x+x,y:p.y+y}));usedWidth=Math.max(usedWidth,x+plan.width);x+=plan.width+gapX;rowHeight=Math.max(rowHeight,plan.height);});
    return {width:usedWidth,height:y+rowHeight,positions};
  }
  root.RWSGraphLayout={topologyPlan};if(typeof module!=='undefined'&&module.exports)module.exports=root.RWSGraphLayout;
})(typeof window!=='undefined'?window:globalThis);
