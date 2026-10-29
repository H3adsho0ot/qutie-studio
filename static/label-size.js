// Editor coordinates use 16 pixels/mm, the print head uses 8 dots/mm.
(function(root){
  function fit(bounds){
    const visible=bounds.filter(b=>[b.x,b.width].every(Number.isFinite)&&b.width>0);
    if(!visible.length)return {lengthMm:10,offsetX:0,overflow:false};
    const left=Math.min(...visible.map(b=>b.x));
    const right=Math.max(...visible.map(b=>b.x+b.width));
    const dots=Math.ceil((right-left+64)/2); // 2 mm margin on each side.
    const lengthMm=Math.max(10,Math.min(80,dots/8));
    const offsetX=dots>640?32-left:(lengthMm*16-(right-left))/2-left;
    return {lengthMm,offsetX,overflow:dots>640};
  }
  const api={fit};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.LabelSize=api;
})(typeof globalThis!=='undefined'?globalThis:this);
