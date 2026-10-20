const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(fetchSpeech, playAudio = async () => {}) {
  const nodes = Object.fromEntries(['ask-form', 'prompt', 'status', 'result', 'cards', 'submit', 'answer',
    'mic-button', 'speak-toggle'].map(id => [id, {value:'Peach wine?',textContent:'',hidden:true,disabled:false,
      handlers:{},addEventListener(name,fn){this.handlers[name]=fn;},replaceChildren(){},focus(){}}]));
  let devicesSpoken = 0;
  const context = {
    document:{body:{dataset:{customVoice:'true'}},getElementById:id=>nodes[id],querySelectorAll:()=>[]},
    window:{addEventListener(){},speechSynthesis:{cancel(){},speak(){devicesSpoken++;}}},
    Intl,URL:{createObjectURL:()=> 'blob:test-audio',revokeObjectURL(){}},AbortController,
    setTimeout,clearTimeout,
    fetch:async path=>path==='/ask'
      ? {ok:true,json:async()=>({response:'Try Peach.',wines:[],speech_token:'signed-token'})}
      : fetchSpeech(),
    Audio:class {constructor(){this.paused=true;} async play(){await playAudio();this.paused=false;} pause(){this.paused=true;}},
  };
  vm.runInNewContext(fs.readFileSync(__dirname + '/../static/concierge.js','utf8'),context);
  return {nodes,devicesSpoken:()=>devicesSpoken};
}

test('custom playback uses the signed reply, reuses downloaded audio, and never uses the device voice',async()=>{
  let calls=0;
  const {nodes,devicesSpoken}=setup(async()=>{calls++;return {ok:true,blob:async()=>({type:'audio/mpeg'})};});
  assert.equal(nodes['speak-toggle'].disabled,true);
  await nodes['ask-form'].handlers.submit({preventDefault(){}});
  await nodes['speak-toggle'].handlers.click();
  assert.equal(nodes['speak-toggle'].textContent,'Stop Charlie’s voice');
  await nodes['speak-toggle'].handlers.click();
  await nodes['speak-toggle'].handlers.click();
  assert.equal(calls,1);
  assert.equal(devicesSpoken(),0);
});

test('provider errors keep recommendations readable and do not substitute a different voice',async()=>{
  const {nodes,devicesSpoken}=setup(async()=>({ok:false,json:async()=>({error:'Voice is busy.'})}));
  await nodes['ask-form'].handlers.submit({preventDefault(){}});
  await nodes['speak-toggle'].handlers.click();
  assert.equal(nodes.answer.textContent,'Try Peach.');
  assert.equal(nodes.result.hidden,false);
  assert.equal(nodes.status.textContent,'Voice is busy.');
  assert.equal(nodes['speak-toggle'].disabled,false);
  assert.equal(devicesSpoken(),0);
});

test('a phone that blocks delayed autoplay gets a second-tap playback option',async()=>{
  let attempts=0;
  const {nodes}=setup(async()=>({ok:true,blob:async()=>({type:'audio/mpeg'})}),async()=>{
    if(++attempts===1)throw new Error('NotAllowedError');
  });
  await nodes['ask-form'].handlers.submit({preventDefault(){}});
  await nodes['speak-toggle'].handlers.click();
  assert.equal(nodes['speak-toggle'].textContent,'▶ Play Charlie’s answer');
  await nodes['speak-toggle'].handlers.click();
  assert.equal(nodes.status.textContent,'Playing Charlie’s answer.');
});

test('a late voice download cannot play an answer replaced by a new question',async()=>{
  let resolveAudio,plays=0;
  const {nodes}=setup(async()=>({ok:true,blob:()=>new Promise(resolve=>{resolveAudio=resolve;})}),async()=>{plays++;});
  await nodes['ask-form'].handlers.submit({preventDefault(){}});
  const pending=nodes['speak-toggle'].handlers.click();
  await new Promise(resolve=>setImmediate(resolve));
  await nodes['ask-form'].handlers.submit({preventDefault(){}});
  resolveAudio({type:'audio/mpeg'});
  await pending;
  assert.equal(plays,0);
});
