const {test}=require('node:test');
const assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const {create}=require('../static/browser-id.js');

test('uses the native UUID generator when available',()=>{
  assert.equal(create({randomUUID(){assert.equal(this.marker,true);return 'native-id'},marker:true}),'native-id');
});

test('plain HTTP fallback produces distinct version 4 UUIDs without randomUUID',()=>{
  const httpCrypto={getRandomValues:bytes=>webcrypto.getRandomValues(bytes)};
  const ids=Array.from({length:1000},()=>create(httpCrypto));
  for(const id of ids)assert.match(id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(new Set(ids).size,ids.length);
});

test('browser script exposes an ID generator with HTTP-only crypto support',()=>{
  const context=vm.createContext({crypto:{getRandomValues:bytes=>webcrypto.getRandomValues(bytes)}});
  vm.runInContext(readFileSync(require.resolve('../static/browser-id.js'),'utf8'),context);
  assert.match(vm.runInContext('BrowserId.create()',context),/^[0-9a-f-]{36}$/);
});
