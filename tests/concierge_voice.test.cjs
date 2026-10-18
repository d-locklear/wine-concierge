const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function setup({supported=true, secure=true, failStart=false, userAgent='Desktop Chrome'}={}) {
  const elements = {};
  function element(id) {
    return elements[id] ||= {value:'', maxLength:2000, hidden:true, disabled:false, textContent:'', listeners:{}, attributes:{}, focused:false,
      addEventListener(name,fn){this.listeners[name]=fn;}, setAttribute(k,v){this.attributes[k]=v;}, focus(){this.focused=true;},
      replaceChildren(){}, append(){}};
  }
  const document={hidden:false, getElementById:element, querySelectorAll:()=>[], listeners:{},
    addEventListener(name,fn){this.listeners[name]=fn;}};
  const sessions=[];
  class Recognition {
    constructor(){sessions.push(this);}
    start(){if(failStart) throw Error('unavailable');}
    abort(){this.aborted=true; this.onend?.();}
  }
  const window={isSecureContext:secure,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}};
  if(supported) window.SpeechRecognition=Recognition;
  const requests=[];
  const timers=[];
  const timer=(fn,delay)=>{const task={fn,delay,cancelled:false};timers.push(task);return task;};
  vm.runInNewContext(fs.readFileSync('static/concierge.js','utf8'),{document,window,navigator:{userAgent},URL,Intl,AbortController,setTimeout:timer,clearTimeout:task=>{if(task)task.cancelled=true;},
    fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({response:'Try our wine.',wines:[]})};}});
  return {elements,document,window,sessions,requests,timers,click:()=>element('microphone').listeners.click(),
    result(text, session=sessions.at(-1)){const item=[{transcript:text}];item.isFinal=true;session.onresult?.({results:[item]});}};
}
test('unsupported and insecure browsers retain text entry without microphone',()=>{
  for(const options of [{supported:false},{secure:false}]) {
    const s=setup(options);assert.equal(s.elements.microphone.hidden,true);assert.equal(s.elements.submit.disabled,false);
  }
});
test('dictation requires a click, fills bounded text, never auto-submits',()=>{
  const s=setup();assert.equal(s.sessions.length,0);s.click();
  assert.equal(s.elements.microphone.attributes['aria-pressed'],'true');
  s.sessions[0].onstart();s.result('peach '.repeat(500));assert.equal(s.elements.prompt.value.length,2000);assert.equal(s.requests.length,0);
  s.sessions[0].onend();assert.equal(s.elements.microphone.attributes['aria-pressed'],'false');
  assert.match(s.elements['voice-status'].textContent,/Review/);
});
test('access denial preserves existing text and allows retry',()=>{
  const s=setup();s.elements.prompt.value='keep this';s.click();
  s.sessions[0].onerror({error:'not-allowed'});s.sessions[0].onend();
  assert.equal(s.elements.prompt.value,'keep this');assert.match(s.elements['voice-status'].textContent,/not allowed/);
  s.click();assert.equal(s.sessions.length,2);
});
test('manual stop and navigation abort listening and ignore late results',()=>{
  for(const action of ['stop','leave']) {
    const s=setup();s.click();const session=s.sessions[0];const late=session.onresult;
    if(action==='stop') s.click();
    if(action==='leave')s.window.listeners.pagehide();
    s.result('late words');assert.equal(session.aborted,true);assert.equal(s.elements.prompt.value,'');
    const item=[{transcript:'also late'}];item.isFinal=true;late({results:[item]});assert.equal(s.elements.prompt.value,'');
  }
});
test('old session cannot change text or reset a new listening session',()=>{
  const s=setup();s.click();const old=s.sessions[0];s.click();s.click();old.onend();old.onerror({error:'network'});
  assert.equal(s.elements.microphone.attributes['aria-pressed'],'true');s.result('sweet wine');assert.equal(s.elements.prompt.value,'sweet wine');
});
test('startup failure and empty recognition recover to typed input',()=>{
  const failed=setup({failStart:true});failed.click();assert.equal(failed.elements.microphone.attributes['aria-pressed'],'false');
  assert.match(failed.elements['voice-status'].textContent,/unavailable/);
  const empty=setup();empty.click();empty.sessions[0].onstart();empty.sessions[0].onend();assert.match(empty.elements['voice-status'].textContent,/No question/);
});
test('manual submission stops microphone and preserves the existing ask contract',async()=>{
  const s=setup();s.click();s.result('I like peach');await s.elements['ask-form'].listeners.submit({preventDefault(){}});
  assert.equal(s.sessions[0].aborted,true);assert.equal(s.requests.length,1);assert.equal(s.requests[0].url,'/ask');
  assert.deepEqual(JSON.parse(s.requests[0].options.body),{prompt:'I like peach'});
  assert.equal(s.elements.submit.disabled,false);assert.equal(s.elements.microphone.disabled,false);
});

test('iPhone permission transitions do not cancel recognition and a hung session times out',()=>{
  const s=setup();s.click();const session=s.sessions[0];
  s.document.hidden=true;
  s.document.listeners.visibilitychange?.();
  assert.equal(session.aborted,undefined);
  session.onstart();
  assert.match(s.elements['voice-status'].textContent,/Listening/);
  s.timers.find(task=>task.delay===20000).fn();
  assert.equal(session.aborted,true);
  assert.match(s.elements['voice-status'].textContent,/keyboard microphone/);
  assert.equal(s.elements.microphone.attributes['aria-pressed'],'false');
});
test('interim recognition fills editable question without interrupting capture',()=>{
  const s=setup();s.click();s.sessions[0].onstart();
  const item=[{transcript:'apple pie'}];item.isFinal=false;
  s.sessions[0].onresult({results:[item]});
  assert.equal(s.elements.prompt.value,'apple pie');
  assert.equal(s.sessions[0].aborted,undefined);
  assert.equal(s.requests.length,0);
});

test('iPhone control opens native keyboard dictation instead of unreliable web speech',()=>{
  const s=setup({userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7) Safari/604.1'});
  assert.equal(s.elements.microphone.hidden,false);
  assert.equal(s.elements.microphone.textContent,'Use iPhone dictation');
  s.click();
  assert.equal(s.elements.prompt.focused,true);
  assert.equal(s.sessions.length,0);
  assert.match(s.elements['voice-status'].textContent,/keyboard/);
  assert.equal(s.requests.length,0);
});
