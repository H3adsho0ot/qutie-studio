const {test}=require('node:test');
const assert=require('node:assert/strict');
const Konva=require('../static/vendor/konva.min.js');
const {targets,snap}=require('../static/snapping.js');

test('aligns both axes to the label centre',()=>{
  assert.deepEqual(snap({x:105,y:85,width:100,height:20},targets(320,192,[])),
    {dx:5,dy:1,guides:[{axis:'x',position:160},{axis:'y',position:96}]});
});

test('uses label edges and includes the six pixel threshold',()=>{
  const stops=targets(320,192,[]);
  assert.deepEqual(snap({x:6,y:176,width:20,height:20},stops),
    {dx:-6,dy:-4,guides:[{axis:'x',position:0},{axis:'y',position:192}]});
  assert.deepEqual(snap({x:7,y:30,width:20,height:20},stops),{dx:0,dy:0,guides:[]});
});

test('aligns an edge to another element and chooses the closest target',()=>{
  const stops=targets(640,192,[{x:250,y:50,width:40,height:30},{x:253,y:130,width:20,height:20}]);
  const result=snap({x:204,y:52,width:40,height:10},stops);
  assert.equal(result.dx,6);
  assert.equal(result.dy,-2);
  assert.deepEqual(result.guides,[{axis:'x',position:250},{axis:'y',position:50}]);
});

test('aligned elements retain zero displacement and invalid targets are ignored',()=>{
  assert.deepEqual(snap({x:20,y:30,width:40,height:10},{x:[NaN,20,21],y:[]}),
    {dx:0,dy:0,guides:[{axis:'x',position:20}]});
});

test('snapping transformed visible bounds preserves rotation, size and stroke',()=>{
  const parent=new Konva.Group({x:43,y:17,scaleX:1.5,scaleY:.8});
  const node=new Konva.Rect({x:20,y:30,width:40,height:20,rotation:32,stroke:'#000',strokeWidth:2});
  parent.add(node);
  const before=node.getClientRect();
  const result=snap(before,{x:[before.x+before.width+4],y:[before.y+before.height/2-3]});
  const position=node.absolutePosition();node.absolutePosition({x:position.x+result.dx,y:position.y+result.dy});
  const after=node.getClientRect();
  assert.ok(Math.abs(after.x-before.x-4)<1e-8);
  assert.ok(Math.abs(after.y-before.y+3)<1e-8);
  assert.ok(Math.abs(after.width-before.width)<1e-8);
  assert.equal(node.rotation(),32);
  assert.equal(node.strokeWidth(),2);
  assert.equal(node.width(),40);
});
