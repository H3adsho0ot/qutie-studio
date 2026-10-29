const {test}=require('node:test');
const assert=require('node:assert/strict');
const Konva=require('../static/vendor/konva.min.js');
const {between}=require('../static/line-geometry.js');

function near(actual,expected){
  assert.ok(Math.abs(actual.x-expected.x)<1e-8);
  assert.ok(Math.abs(actual.y-expected.y)<1e-8);
}
function endpoints(line){
  const matrix=line.getAbsoluteTransform(),points=line.points();
  return [0,2].map(i=>matrix.point({x:points[i],y:points[i+1]}));
}

test('endpoint geometry handles horizontal, vertical, diagonal and reversed lines',()=>{
  for(const end of [{x:200,y:30},{x:20,y:180},{x:-120,y:-80},{x:20,y:30}]){
    const start={x:20,y:30},line=new Konva.Line(between(start,end));
    const actual=endpoints(line);
    near(actual[0],start);near(actual[1],end);
    assert.ok(Number.isFinite(line.rotation()));
  }
});

test('editing an endpoint preserves the other end after rotation, scale and offsets',()=>{
  const line=new Konva.Line({x:41,y:27,rotation:37,scaleX:2,scaleY:.6,
    skewX:.2,offsetX:8,offsetY:3,points:[-12,9,84,61],strokeWidth:4,strokeScaleEnabled:false});
  const original=endpoints(line),newEnd={x:340,y:130};
  line.setAttrs(between(original[0],newEnd));
  near(endpoints(line)[0],original[0]);near(endpoints(line)[1],newEnd);
  assert.equal(line.strokeWidth(),4);
  assert.equal(line.strokeScaleEnabled(),false);
});

test('moving the start preserves the far endpoint and keeps layer translation separate',()=>{
  const parent=new Konva.Group({x:56,y:14});
  const line=new Konva.Line({points:[0,0,220,0],strokeWidth:3,strokeScaleEnabled:false});
  parent.add(line);
  const end={x:220,y:0};
  line.setAttrs(between({x:-30,y:70},end));
  near(endpoints(line)[0],{x:26,y:84});near(endpoints(line)[1],{x:276,y:14});
  assert.equal(line.strokeWidth(),3);
});
