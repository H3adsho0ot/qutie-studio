// All geometry is in stage coordinates, including rotated objects' visible bounds.
(function(root){
  function anchors(start,size){return [start,start+size/2,start+size]}
  function targets(width,height,boxes){
    return {x:[0,width/2,width,...boxes.flatMap(b=>anchors(b.x,b.width))],
      y:[0,height/2,height,...boxes.flatMap(b=>anchors(b.y,b.height))]};
  }
  function snap(box,stops,tolerance=6){
    const result={dx:0,dy:0,guides:[]};
    for(const [axis,start,size,delta] of [['x',box.x,box.width,'dx'],['y',box.y,box.height,'dy']]){
      let best=null;
      for(const edge of anchors(start,size))for(const position of stops[axis]){
        const distance=position-edge;
        if(Number.isFinite(distance)&&Math.abs(distance)<=tolerance&&(!best||Math.abs(distance)<Math.abs(best.distance))){
          best={position,distance};
        }
      }
      if(best){result[delta]=best.distance;result.guides.push({axis,position:best.position})}
    }
    return result;
  }
  const api={targets,snap};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.Snapping=api;
})(typeof globalThis!=='undefined'?globalThis:this);
