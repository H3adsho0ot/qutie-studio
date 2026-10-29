const $=id=>document.getElementById(id);
const labelFontsReady=Promise.all(['normal 400','normal 700','italic 400','italic 700'].map(style=>document.fonts.load(style+' 16px Noto')));
const stage=new Konva.Stage({container:'canvas',width:640,height:192});
const layer=new Konva.Layer();stage.add(layer);
const rasterLayer=new Konva.Layer({listening:false,imageSmoothingEnabled:false});stage.add(rasterLayer);
const rasterNode=new Konva.Image({listening:false});rasterLayer.add(rasterNode);
const selectionLayer=new Konva.Layer();stage.add(selectionLayer);
const tr=new Konva.Transformer({rotateEnabled:true,keepRatio:false,enabledAnchors:['top-left','top-right','bottom-left','bottom-right']});selectionLayer.add(tr);
let selected=null,templateId=crypto.randomUUID(),history=[],historyIndex=-1,restoring=false,revision=0,currentPrintId=null,lastPrintState=null,printSubmitting=false;
let renderTimer=null,renderRunning=false,rendered=null,renderEpoch=0,renderError=false;
let autoLength=false,manualLength=40,autoOverflow=false,sizeError=false;
const notice=(text,error=false)=>{$('notice').textContent=text;$('notice').classList.toggle('error',error)};
async function api(path,options={}){let r=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});if(!r.ok){let e=await r.json().catch(()=>({detail:r.statusText}));throw Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail))}return r.json()}
function action(id,fn){$(id).onclick=()=>Promise.resolve().then(fn).catch(e=>notice(e.message,true))}
function ask(question,initial=null){return new Promise(resolve=>{const dialog=document.createElement('dialog');dialog.innerHTML='<form><h2></h2><label>Content<input name="value" type="text"></label><div class="dialog-actions"><button type="button">Cancel</button><button type="submit" class="primary">OK</button></div></form>';dialog.querySelector('h2').textContent=question;const input=dialog.querySelector('input');input.value=initial??'';dialog.querySelector('label').hidden=initial===null;dialog.querySelector('button').onclick=()=>dialog.close('cancel');dialog.querySelector('form').onsubmit=e=>{e.preventDefault();dialog.close('ok')};dialog.onclose=()=>{resolve(dialog.returnValue==='ok'?(initial===null?true:input.value):null);dialog.remove()};document.body.append(dialog);dialog.showModal();(initial===null?dialog.querySelector('button[type=submit]'):input).focus()})}
function nodes(){return layer.getChildren().filter(n=>n!==tr)}
function invalidate(){
  resize();
  revision++;rendered=null;$('print').disabled=true;
  $('canvas').setAttribute('aria-busy','true');
  scheduleRaster();
}
function scheduleRaster(){
  if(renderTimer!==null||renderRunning||restoring)return;
  renderTimer=setTimeout(()=>{renderTimer=null;renderEditor()},80);
}
async function renderEditor(){
  if(renderRunning||restoring)return;
  renderRunning=true;
  const version=revision,epoch=renderEpoch;
  let url=null;
  try{
    await labelFontsReady;
    const body={image:layer.toDataURL({x:0,y:0,width:stage.width(),height:stage.height(),pixelRatio:.5}),length_mm:Number($('length').value),threshold:Number($('threshold').value),dither:$('dither').checked,length_scale:Number($('lengthScale').value)};
    const response=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!response.ok){const error=await response.json();throw Error(typeof error.detail==='string'?error.detail:'Could not create the print view.')}
    const digest=response.headers.get('X-Raster-SHA256');
    const blob=await response.blob();
    url=URL.createObjectURL(blob);
    const image=new Image();image.src=url;await image.decode();
    if(epoch!==renderEpoch)return;
    // Keep editing handles in their own layer; only the printer raster is visible.
    rasterNode.setAttrs({image,x:0,y:stage.height(),width:image.width,height:image.height,rotation:-90,scaleX:stage.height()/image.width,scaleY:stage.width()/image.height});
    rasterLayer.draw();
    if(version===revision){
      rendered={version,body,digest};$('canvas').setAttribute('aria-busy','false');
      $('print').disabled=printSubmitting||printerBusy||autoOverflow;
      if(renderError){notice('');renderError=false}
    }
  }catch(e){if(epoch===renderEpoch&&version===revision){rendered=null;renderError=true;notice('Print view unavailable: '+e.message,true)}}
  finally{
    if(url)URL.revokeObjectURL(url);
    renderRunning=false;
    if(revision!==version)scheduleRaster();
  }
}
function doc(){return {version:1,autoLength,manualLength,lengthScale:Number($('lengthScale').value),length:Number($('length').value),feed:Number($('feed').value),threshold:Number($('threshold').value),dither:$('dither').checked,nodes:nodes().map(n=>({type:n.getClassName(),attrs:{...n.getAttrs(),image:undefined}}))}}
function record(){invalidate();if(restoring)return;history=history.slice(0,historyIndex+1);history.push(JSON.stringify(doc()));historyIndex=history.length-1;$('undo').disabled=historyIndex<1;$('redo').disabled=true}
function select(n){
  selected=n;tr.nodes(n?[n]:[]);$('elementProps').hidden=!n;$('selectionHint').hidden=!!n;
  const type=n?.getClassName();
  const text=type==='Text',qr=type==='Image'&&n.getAttr('qrText')!==undefined;
  const stroked=type==='Rect'||type==='Line';
  $('contentField').hidden=!(text||qr);
  $('fontSizeField').hidden=!text;
  $('fontStyleField').hidden=!text;
  for(const style of ['bold','italic'])$(style).setAttribute('aria-pressed',String(text&&n.fontStyle().split(/\s+/).includes(style)));
  $('strokeWidthField').hidden=!stroked;
  $('contentLabel').textContent=qr?'QR content':'Text';
  $('elementTitle').textContent=!n?'Selected element':qr?'QR code':({Text:'Text',Image:'Image',Rect:'Frame',Line:'Line'}[type]||'Selected element');
  if(n){
    $('content').value=qr?n.getAttr('qrText'):text?n.text():'';
    if(text)$('fontSize').value=n.fontSize()/2;
    if(stroked)$('strokeWidth').value=n.strokeWidth();
    $('rotation').value=n.rotation();
  }
  selectionLayer.batchDraw();layer.batchDraw();
}
async function hydrate(n){if(n.getClassName()==='Image'){let image=new Image();image.src=n.getAttr('src');await image.decode();n.image(image)}}
function wire(n){n.draggable(true);n.on('click tap',()=>select(n));n.on('dragmove transform',invalidate);n.on('dragend transformend',()=>{record();select(n)})}
function resize(){
  let length=Math.max(10,Math.min(80,Number($('length').value)||40));
  autoOverflow=false;
  if(autoLength){
    const fit=LabelSize.fit(nodes().map(n=>n.getClientRect({relativeTo:layer})));
    length=fit.lengthMm;autoOverflow=fit.overflow;layer.x(fit.offsetX);
  }else{layer.x(0)}
  $('length').value=length;$('length').disabled=autoLength;
  $('autoLength').setAttribute('aria-pressed',String(autoLength));
  stage.width(length*16);
  const feed=Math.max(0,Math.min(30,Number($('feed').value)||0));
  $('feed').value=feed;
  $('feedSummary').textContent='+ '+feed+' mm feed';
  $('feedMargin').style.width=feed*16+'px';
  $('feedMargin').hidden=feed===0;
  $('feedMargin').setAttribute('aria-label',feed+' mm blank feed after printing');
  document.querySelector('.measure').style.width=stage.width()+feed*16+'px';
  if(autoOverflow){notice('The content including margins exceeds 80 mm. Please reduce its size.',true);sizeError=true}
  else if(sizeError){notice('');sizeError=false}
  layer.draw();selectionLayer.batchDraw();
}
async function restore(d,track=true){if(d.version!==1||!Array.isArray(d.nodes)||d.nodes.length>200)throw Error('Invalid template format');restoring=true;renderEpoch++;rendered=null;rasterNode.image(null);rasterLayer.draw();try{nodes().forEach(n=>n.destroy());select(null);for(const key of ['length','feed','threshold','lengthScale'])$(key).value=d[key]??({length:40,feed:14,threshold:160,lengthScale:100}[key]);$('dither').checked=!!d.dither;autoLength=!!d.autoLength;manualLength=Number(d.manualLength??d.length??40);resize();for(const item of d.nodes){if(!['Text','Image','Rect','Line'].includes(item.type))throw Error('Unknown element');const attrs={...item.attrs};if(item.type==='Image'&&!/^data:image\/(png|jpeg);base64,/.test(attrs.src||''))throw Error('Template contains an invalid image');let n=Konva.Node.create({className:item.type,attrs});await hydrate(n);wire(n);layer.add(n)}tr.moveToTop();layer.draw()}finally{restoring=false}invalidate();if(track)record()}
function add(n){wire(n);layer.add(n);tr.moveToTop();select(n);record()}
async function imageNode(src,extra={}){let im=new Image();im.src=src;await im.decode();let width=Math.min(140,im.width),height=width*im.height/im.width;if(height>150){width*=150/height;height=150}add(new Konva.Image({x:25,y:20,width,height,image:im,src,...extra}))}
async function dataURL(src){let blob=await(await fetch(src)).blob();return new Promise((resolve,reject)=>{let r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(blob)})}
async function qrSource(text){return dataURL('/api/qr?text='+encodeURIComponent(text))}
stage.on('click tap',e=>{if(e.target===stage)select(null)});
action('editName',()=>{$('name').focus();$('name').select()});
action('settings',()=>$('settingsDialog').showModal());
action('settingsClose',()=>$('settingsDialog').close());
$('settingsDialog').addEventListener('click',event=>{
  if(event.target!==$('settingsDialog'))return;
  const box=$('settingsDialog').getBoundingClientRect();
  if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)$('settingsDialog').close();
});

action('text',async()=>{await labelFontsReady;add(new Konva.Text({x:24,y:50,text:'Your text',fontFamily:'Noto',fontSize:48,fill:'#000',padding:2}))});
for(const style of ['bold','italic'])action(style,async()=>{
  await labelFontsReady;
  if(selected?.getClassName()!=='Text')return;
  const styles=new Set(selected.fontStyle().split(/\s+/));
  if(styles.has(style))styles.delete(style);else styles.add(style);
  selected.fontStyle(['bold','italic'].filter(value=>styles.has(value)).join(' ')||'normal');
  record();select(selected);
});
action('rect',()=>add(new Konva.Rect({x:20,y:20,width:240,height:150,stroke:'#000',strokeWidth:2})));
action('line',()=>add(new Konva.Line({x:25,y:96,points:[0,0,220,0],stroke:'#000',strokeWidth:2})));
action('qr',async()=>{const text=await ask('QR content','https://example.org');if(text)await imageNode(await qrSource(text),{width:176,height:176,y:8,qrText:text})});
action('image',()=>$('imageFile').click());$('imageFile').onchange=async e=>{try{let f=e.target.files[0];if(!f)return;if(f.size>8000000)throw Error('Image too large (max. 8 MB)');let src=await new Promise(resolve=>{let r=new FileReader();r.onload=()=>resolve(r.result);r.readAsDataURL(f)});let saved=await api('/api/images',{method:'POST',body:JSON.stringify({image:src})});await imageNode(await dataURL(saved.url))}catch(e){notice(e.message,true)}finally{$('imageFile').value=''}};
action('remove',()=>{if(selected){selected.destroy();select(null);record()}});
action('duplicate',async()=>{if(selected){let n=selected.clone({x:selected.x()+12,y:selected.y()+12});await hydrate(n);add(n)}});
action('front',()=>{if(selected){selected.moveToTop();tr.moveToTop();record()}});
action('back',()=>{if(selected){selected.moveToBottom();record()}});
function centerSelected(axis){
  if(!selected)return;
  const box=selected.getClientRect({relativeTo:layer});
  if(axis==='vertical')selected.y(selected.y()+(stage.height()-box.height)/2-box.y);
  else if(autoLength){
    // Auto width follows the union of all elements. Centre against the other
    // elements so the result stays centred after the label is fitted again.
    const others=nodes().filter(n=>n!==selected).map(n=>n.getClientRect({relativeTo:layer})).filter(b=>b.width>0);
    if(others.length){
      const left=Math.min(...others.map(b=>b.x)),right=Math.max(...others.map(b=>b.x+b.width));
      selected.x(selected.x()+(left+right-box.width)/2-box.x);
    }
  }else selected.x(selected.x()+(stage.width()-box.width)/2-box.x);
  record();select(selected);
}
action('centerHorizontal',()=>centerSelected('horizontal'));
action('centerVertical',()=>centerSelected('vertical'));
$('content').onchange=async()=>{try{if(!selected)return;if(selected.getAttr('qrText')!==undefined){const src=await qrSource($('content').value);selected.setAttrs({src,qrText:$('content').value});await hydrate(selected)}else if(selected.text)selected.text($('content').value);record();layer.draw()}catch(e){notice(e.message,true)}};
for(const [id,method] of [['fontSize','fontSize'],['rotation','rotation'],['strokeWidth','strokeWidth']])$(id).onchange=()=>{if(selected&&typeof selected[method]==='function'){selected[method](Number($(id).value)*(method==='fontSize'?2:1));record();layer.draw()}};
$('length').onchange=()=>{manualLength=Math.max(10,Math.min(80,Number($('length').value)||40));$('length').value=manualLength;record()};
action('autoLength',()=>{if(!autoLength)manualLength=Number($('length').value);autoLength=!autoLength;if(!autoLength)$('length').value=manualLength;record()});for(const id of ['feed','threshold','dither','lengthScale'])$(id).onchange=record;
action('undo',async()=>{if(historyIndex>0){await restore(JSON.parse(history[--historyIndex]),false);$('undo').disabled=historyIndex<1;$('redo').disabled=false}});
action('redo',async()=>{if(historyIndex<history.length-1){await restore(JSON.parse(history[++historyIndex]),false);$('redo').disabled=historyIndex===history.length-1;$('undo').disabled=false}});
let openTemplateMenu=null;
function closeTemplateMenu(focus=false){
  if(!openTemplateMenu)return;
  const {menu,toggle}=openTemplateMenu;
  menu.hidden=true;toggle.setAttribute('aria-expanded','false');
  openTemplateMenu=null;if(focus)toggle.focus();
}
document.addEventListener('pointerdown',event=>{
  if(openTemplateMenu&&!openTemplateMenu.row.contains(event.target))closeTemplateMenu();
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&openTemplateMenu){event.preventDefault();closeTemplateMenu(true)}
});
function downloadTemplate(value){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify({name:value.name,document:value.document},null,2)],{type:'application/json'}));
  a.download='qutie-template.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}
async function templateAction(item,operation){
  if(operation==='delete'){
    if(!await ask('Delete template “'+item.name+'”?'))return;
    await api('/api/templates/'+item.id,{method:'DELETE'});
    if(templateId===item.id)templateId=crypto.randomUUID();
    await listTemplates();notice('Template deleted. Your current draft has been kept.');
    return;
  }
  const value=await api('/api/templates/'+item.id);
  if(operation==='export'){downloadTemplate(value);return}
  await api('/api/templates/'+crypto.randomUUID(),{method:'PUT',body:JSON.stringify({name:value.name+' – Copy',document:value.document})});
  await listTemplates();notice('Template copy created.');
}
async function listTemplates(){
  const items=await api('/api/templates');closeTemplateMenu();$('templates').replaceChildren();
  for(const item of items){
    const row=document.createElement('div');row.className='template-row';
    const b=document.createElement('button');b.className='template-open';b.textContent=item.name;
    b.onclick=async()=>{try{
      closeTemplateMenu();if(!await ask('Replace the current draft with this template?'))return;
      const v=await api('/api/templates/'+item.id);await restore(v.document);templateId=v.id;$('name').value=v.name;
      history=[JSON.stringify(doc())];historyIndex=0;notice('Template loaded.');
    }catch(e){notice(e.message,true)}};
    const toggle=document.createElement('button');toggle.className='template-menu-toggle';toggle.type='button';
    toggle.textContent='⋮';toggle.title='Template actions';toggle.setAttribute('aria-label','Actions for '+item.name);
    toggle.setAttribute('aria-haspopup','menu');toggle.setAttribute('aria-expanded','false');
    const menu=document.createElement('div');menu.className='template-menu';menu.hidden=true;
    menu.id='template-menu-'+item.id;menu.setAttribute('role','menu');menu.setAttribute('aria-label','Actions for '+item.name);
    toggle.setAttribute('aria-controls',menu.id);
    const showMenu=()=>{closeTemplateMenu();menu.hidden=false;toggle.setAttribute('aria-expanded','true');openTemplateMenu={row,menu,toggle};menu.querySelector('button').focus()};
    toggle.onclick=()=>{if(openTemplateMenu?.menu===menu)closeTemplateMenu(true);else showMenu()};
    toggle.onkeydown=event=>{if(event.key==='ArrowDown'){event.preventDefault();showMenu()}};
    row.oncontextmenu=event=>{event.preventDefault();showMenu()};
    for(const [operation,label,path] of [
      ['export','Export','M12 3v12m-4-4 4 4 4-4M5 16v5h14v-5'],
      ['copy','Create copy','M9 9h12v12H9zM15 5V3H3v12h2'],
      ['delete','Delete','M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7']
    ]){
      const button=document.createElement('button');button.type='button';button.setAttribute('role','menuitem');
      if(operation==='delete')button.className='danger';
      button.innerHTML='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'+path+'"/></svg><span></span>';
      button.querySelector('span').textContent=label;
      button.onclick=async()=>{closeTemplateMenu(true);toggle.disabled=true;try{await templateAction(item,operation)}catch(e){notice(e.message,true)}finally{toggle.disabled=false}};
      menu.append(button);
    }
    menu.onkeydown=event=>{
      const buttons=[...menu.querySelectorAll('button')],index=buttons.indexOf(document.activeElement);
      if(event.key==='Tab'){closeTemplateMenu();return}
      const next=event.key==='ArrowDown'?(index+1)%buttons.length:event.key==='ArrowUp'?(index+buttons.length-1)%buttons.length:event.key==='Home'?0:event.key==='End'?buttons.length-1:null;
      if(next!==null){event.preventDefault();buttons[next].focus()}
    };
    row.append(b,toggle,menu);$('templates').append(row);
  }
}
async function save(){await api('/api/templates/'+templateId,{method:'PUT',body:JSON.stringify({name:$('name').value,document:doc()})});await listTemplates();notice('Template saved on the server.')}
action('save',save);
action('new',async()=>{if(!await ask('Start a new draft? Unsaved changes will be lost.'))return;await restore({version:1,autoLength:true,manualLength:40,length:40,nodes:[]});templateId=crypto.randomUUID();$('name').value='New template';history=[JSON.stringify(doc())];historyIndex=0});
action('import',()=>$('importFile').click());$('importFile').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;if(f.size>10000000)throw Error('Template too large');const value=JSON.parse(await f.text());await restore(value.document);templateId=crypto.randomUUID();$('name').value=value.name||'Imported template';notice('Template imported. Save it to keep it.')}catch(e){notice(e.message,true)}finally{$('importFile').value=''}};
action('print',async()=>{
  const snapshot=rendered;
  if(printSubmitting||autoOverflow||!snapshot||snapshot.version!==revision)return;
  printSubmitting=true;$('print').disabled=true;
  try{
    const preview=await api('/api/previews',{method:'POST',body:JSON.stringify(snapshot.body)});
    if(snapshot.version!==revision){notice('The draft changed. Please print the updated draft.');return}
    if(!snapshot.digest||preview.sha256!==snapshot.digest)throw Error('The print view does not match the print data. Please edit the draft again.');
    const job=await api('/api/jobs',{method:'POST',body:JSON.stringify({preview_id:preview.id,feed_mm:Number($('feed').value),request_id:crypto.randomUUID()})});
    currentPrintId=job.id;lastPrintState=null;notice('Processing print job …');await refreshJobs();
  }catch(e){notice('The print job could not be confirmed. Check the label before printing again. '+e.message,true)}
  finally{printSubmitting=false;$('print').disabled=autoOverflow||!rendered||rendered.version!==revision||printerBusy}
});
async function refreshJobs(){
  const jobs=await api('/api/jobs');
  const busy=jobs.some(j=>['queued','printing'].includes(j.state));
  $('print').disabled=autoOverflow||busy||printSubmitting||!rendered||rendered.version!==revision;
  if(busy!==printerBusy){printerBusy=busy;if(busy)showPrinter({...lastPrinterStatus,busy:true,ready:false});else refreshPrinter()}
  const current=jobs.find(j=>j.id===currentPrintId);
  if(current&&current.state!==lastPrintState){
    lastPrintState=current.state;
    notice(current.state==='queued'?'Waiting for printer …':current.state==='printing'?'Printing label …':current.message,current.state==='unknown');
    if(['sent','unknown'].includes(current.state))currentPrintId=null;
  }
}
let printerChecking=false,printerBusy=false,lastPrinterStatus={};
function showPrinter(p){
  lastPrinterStatus=p;
  const state=p.busy?'busy':!p.connected?'offline':p.ready?'ready':'problem';
  $('printerStatus').dataset.state=state;
  $('printerModel').textContent=p.model||'Qutie';
  $('printerFirmware').textContent=p.firmware?'Firmware '+p.firmware:'';
  $('printerState').textContent=p.busy?'Printing …':!p.connected?'Offline':p.ready?'Ready':(p.problems?.join(', ')||'Not ready');
  $('printerStatus').title=p.message||'';
  const battery=p.battery;
  const valid=(p.connected||p.busy)&&Number.isFinite(battery)&&battery>=0&&battery<=100;
  $('printerBattery').hidden=!valid;
  if(valid){$('batteryText').textContent=battery+' %';$('batteryFill').style.width=battery+'%';$('batteryIcon').setAttribute('aria-label','Battery '+battery+' percent');$('printerBattery').dataset.level=battery<=20?'low':battery<=50?'medium':'high'}
}
async function refreshPrinter(){
  if(printerChecking)return;
  if(printerBusy){showPrinter({...lastPrinterStatus,busy:true,ready:false});return}
  printerChecking=true;
  try{const status=await api('/api/printer');showPrinter(printerBusy?{...status,busy:true,ready:false}:status)}catch(e){showPrinter({connected:false,message:'Server unavailable: '+e.message})}
  finally{printerChecking=false}
}
(async function pollPrinter(){await refreshPrinter();setTimeout(pollPrinter,30000)})();
document.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;if(e.key==='Delete')$('remove').click();if(e.ctrlKey&&e.key==='z'){e.preventDefault();$(e.shiftKey?'redo':'undo').click()}});
(async()=>{await labelFontsReady;await restore({version:1,autoLength:true,manualLength:40,length:40,nodes:[{type:'Text',attrs:{x:30,y:53,text:'Everything in its place.',fontFamily:'Noto',fontSize:44,fill:'#000'}}]});await listTemplates();await refreshJobs();setInterval(()=>refreshJobs().catch(()=>{}),2500)})().catch(e=>notice(e.message,true));
