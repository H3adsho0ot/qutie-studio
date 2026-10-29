// Represent a straight line by its two endpoints in the parent layer.
(function(root){
  function between(start,end){
    const dx=end.x-start.x,dy=end.y-start.y;
    return {x:start.x,y:start.y,points:[0,0,Math.hypot(dx,dy),0],
      rotation:Math.atan2(dy,dx)*180/Math.PI,
      scaleX:1,scaleY:1,skewX:0,skewY:0,offsetX:0,offsetY:0};
  }
  const api={between};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.LineGeometry=api;
})(typeof globalThis!=='undefined'?globalThis:this);
