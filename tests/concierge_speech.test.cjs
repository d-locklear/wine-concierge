const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(fetchSpeech, playAudio = async () => {}, reply = {response:'Try Peach.',wines:[],speech_token:'signed-token'}) {
  const nodes = Object.fromEntries(['ask-form', 'prompt', 'status', 'result', 'cards', 'submit', 'answer',
    'mic-button', 'speak-toggle', 'location', 'result-heading'].map(id => [id, {value:'Peach wine?',textContent:'',hidden:true,disabled:false,
      handlers:{},addEventListener(name,fn){this.handlers[name]=fn;},replaceChildren(){},focus(){}}]));
  nodes.location.value = '';
  nodes.cards.children = []; nodes.cards.append = function(child){this.children.push(child);};
  nodes.cards.replaceChildren = function(){this.children=[];};
  let devicesSpoken = 0;
  const context = {
    document:{body:{dataset:{customVoice:'true'}},getElementById:id=>nodes[id],querySelectorAll:()=>[], createElement:tag=>({tag,children:[],textContent:'',append(child){this.children.push(child);}})},
    window:{addEventListener(){},speechSynthesis:{cancel(){},speak(){devicesSpoken++;}}},
    Intl,URL:Object.assign(URL,{createObjectURL:()=> 'blob:test-audio',revokeObjectURL(){}}),AbortController,
    setTimeout,clearTimeout,
    fetch:async path=>path==='/ask'
      ? {ok:true,json:async()=>reply}
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


test('buying replies render public location cards safely and preserve speech',async()=>{
  const reply = {response:'Find our wines at Food Lion in North Carolina.',wines:[],speech_token:'signed-token',
    locations:[{name:'Food Lion — all North Carolina stores',kind:'chain',coverage:'North Carolina only',
      url:'https://stores.foodlion.com/nc',checked_on:'2026-10-22'},
      {name:'<img onerror=bad()>',kind:'retailer',url:'javascript:bad()',checked_on:'2026-10-22'}]};
  const {nodes}=setup(async()=>({ok:true,blob:async()=>({type:'audio/mpeg'})}),async()=>{},reply);
  nodes.prompt.value=''; nodes.location.value='Cary';
  await nodes['ask-form'].handlers.submit({preventDefault(){}});
  assert.equal(nodes['result-heading'].textContent,'Where to buy');
  assert.equal(nodes.cards.children.length,2);
  const links=nodes.cards.children.flatMap(c=>c.children).filter(c=>c.tag==='a');
  assert.equal(links.length,1);
  assert.equal(links[0].href,'https://stores.foodlion.com/nc');
  assert.equal(nodes.cards.children[1].children[0].textContent,'<img onerror=bad()>');
  assert.equal(nodes['speak-toggle'].disabled,false);
  await nodes['speak-toggle'].handlers.click();
  assert.equal(nodes.status.textContent,'Playing Charlie’s answer.');
});
