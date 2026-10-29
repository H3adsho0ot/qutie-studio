const {test}=require('node:test');
const assert=require('node:assert/strict');
const {fit}=require('../static/label-size.js');

test('empty label has a usable minimum size',()=>{
  assert.deepEqual(fit([]),{lengthMm:10,offsetX:0,overflow:false});
});
test('short content stays centred when minimum label width adds space',()=>{
  const result=fit([{x:30,width:32}]);
  assert.equal(result.lengthMm,10);
  assert.equal(30+result.offsetX+32/2,result.lengthMm*16/2);
});
test('fits all elements with two millimetres on both sides',()=>{
  const result=fit([{x:30,width:160},{x:210,width:160}]);
  assert.equal(result.lengthMm,25.25);
  assert.equal(result.offsetX,2);
  assert.equal(result.overflow,false);
});
test('negative bounds from rotation are included',()=>{
  const result=fit([{x:-48,width:320}]);
  assert.equal(result.lengthMm,24);
  assert.equal(result.offsetX,80);
});
test('rounds upwards to whole printer dots',()=>{
  const result=fit([{x:10.3,width:202.1}]);
  assert.equal(result.lengthMm*8,134);
  assert.ok(result.lengthMm*16>=202.1+64);
});
test('grows and shrinks with content and reports overflow',()=>{
  assert.ok(fit([{x:0,width:500}]).lengthMm>fit([{x:0,width:200}]).lengthMm);
  assert.deepEqual(fit([{x:0,width:1300}]),{lengthMm:80,offsetX:32,overflow:true});
});
