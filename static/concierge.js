'use strict';
const form = document.getElementById('ask-form');
const promptInput = document.getElementById('prompt');
const statusLine = document.getElementById('status');
const result = document.getElementById('result');
const cards = document.getElementById('cards');
const submit = document.getElementById('submit');
const shopUrl = 'https://vinoshipper.com/shop/charlie_t_locklear_vineyard_winery';
const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents / 100);
function paragraph(parent, text, className) {
  const element = document.createElement('p');
  element.textContent = text;
  if (className) element.className = className;
  parent.append(element);
}
function safePurchaseUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' && !url.username && !url.password &&
        ['vinoshipper.com','locklearwinery.com','www.locklearwinery.com'].includes(url.hostname)) return url.href;
  } catch (_) { /* Use the verified storefront when a product URL is missing. */ }
  return shopUrl;
}
function renderWine(wine) {
  const card = document.createElement('article');
  card.className = 'wine-card';
  const name = document.createElement('h3'); name.textContent = wine.name; card.append(name);
  paragraph(card, [wine.sweetness, wine.bottle_ml ? `${wine.bottle_ml} mL` : null].filter(Boolean).join(' · '), 'details');
  paragraph(card, wine.description || wine.flavor_profile || 'Explore this wine with our family.');
  if (wine.pairings) paragraph(card, wine.pairings);
  if (wine.serving) paragraph(card, `Serve: ${wine.serving}`, 'details');
  if (Number.isInteger(wine.online_price_cents) && wine.online_checked_on) {
    paragraph(card, `${money(wine.online_price_cents)} online · checked ${wine.online_checked_on}`, 'price');
    paragraph(card, 'Price before shipping and applicable taxes; confirm in the shop.', 'details');
  }
  if (wine.online_status === 'sold_out' && wine.online_checked_on) {
    paragraph(card, `Marked sold out online when checked ${wine.online_checked_on}. Check the shop for updates.`, 'stock');
  } else paragraph(card, 'Check the shop for current online availability.', 'stock');
  paragraph(card, 'Winery stock: please confirm with our family.', 'stock');
  const link = document.createElement('a'); link.href = safePurchaseUrl(wine.purchase_url);
  link.target = '_blank'; link.rel = 'noopener';
  link.textContent = wine.purchase_url ? 'View this wine on Vinoshipper ↗' : 'Browse the online shop ↗';
  card.append(link); cards.append(card);
}
for (const button of document.querySelectorAll('[data-prompt]')) {
  button.addEventListener('click', () => { promptInput.value = button.dataset.prompt; promptInput.focus(); });
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submit.disabled || !promptInput.value.trim()) return;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 65000);
  stopGuestListening();
  microphone.disabled = true;
  submit.disabled = true; result.hidden = true; statusLine.textContent = 'Finding a wine for you…';
  try {
    const response = await fetch('/ask', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:promptInput.value.trim()}),signal:controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'We could not complete that recommendation. Please try again.');
    if (typeof data.response !== 'string' || !Array.isArray(data.wines)) throw new Error('Please try your question again.');
    document.getElementById('answer').textContent = data.response;
    cards.replaceChildren(); data.wines.forEach(renderWine);
    result.hidden = false; statusLine.textContent = 'Your recommendations are ready.';
  } catch (error) {
    statusLine.textContent = error.name === 'AbortError' ? 'This is taking longer than expected. Please try again or browse our wines below.' : (error instanceof TypeError ? 'We could not connect. Please try again or browse our wines below.' : error.message);
  } finally { clearTimeout(timeout); submit.disabled = false; microphone.disabled = false; }
});


// Guest dictation only: no owner-assistant session, voice clone or audio upload to /ask.
const microphone = document.getElementById('microphone');
const voiceNote = document.getElementById('voice-note');
const voiceStatus = document.getElementById('voice-status');
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const onIPhone = /iPhone|iPad|iPod/.test(navigator.userAgent);
let recognition = null;
let listening = false;
let receivedSpeech = false;
let voiceFailed = false;
let listeningTimeout = null;
function stopGuestListening() {
  if (!recognition || !listening) return;
  listening = false;
  clearTimeout(listeningTimeout);
  listeningTimeout = null;
  microphone.textContent = 'Speak your question';
  microphone.setAttribute('aria-pressed', 'false');
  // Ignore late recognition events after navigation, hiding or manual submission.
  recognition.onresult = null;
  recognition.abort();
}
if (onIPhone) {
  microphone.hidden = false;
  microphone.textContent = 'Use iPhone dictation';
  voiceNote.textContent = 'Tap this button, then tap the microphone on your iPhone keyboard to speak your question. Review the words before selecting Find my wine.';
  microphone.addEventListener('click', () => {
    promptInput.focus();
    voiceStatus.textContent = 'Tap the microphone on your iPhone keyboard and speak.';
  });
} else if (SpeechRecognition && window.isSecureContext) {
  microphone.hidden = false;
  voiceNote.textContent = 'Your browser may process speech online. Review the words, then select Find my wine. On iPhone, you can also tap the keyboard microphone in the question field. Replies are text for now.';
  microphone.addEventListener('click', () => {
    if (listening) {
      stopGuestListening();
      voiceStatus.textContent = 'Microphone stopped. You can edit your question.';
      return;
    }
    if (submit.disabled) return;
    receivedSpeech = false;
    voiceFailed = false;
    try {
      recognition = new SpeechRecognition();
      recognition.lang = 'en-US';
      recognition.continuous = false;
      recognition.interimResults = false;
      const session = recognition;
      session.onresult = event => {
        if (recognition !== session || !listening) return;
        const words = Array.from(event.results).map(item => item[0]?.transcript || '')
          .join(' ').trim();
        if (!words) return;
        promptInput.value = words.slice(0, promptInput.maxLength);
        receivedSpeech = true;
        voiceStatus.textContent = 'Question captured. Review it, then select Find my wine.';
        // Focusing the textarea can dismiss the iPhone speech capture UI.
      };
      session.onerror = event => {
        if (recognition !== session) return;
        voiceFailed = true;
        const messages = {
          'not-allowed': 'Microphone access was not allowed. You can type your question.',
          'service-not-allowed': 'Speech recognition is unavailable here. You can type your question.',
          'audio-capture': 'No microphone is available. You can type your question.',
          'no-speech': 'No speech was detected. Try again or type your question.',
          'network': 'Speech recognition could not connect. You can type your question.'
        };
        if (event.error !== 'aborted') voiceStatus.textContent = messages[event.error] || 'Speech recognition stopped. Try again or type your question.';
        stopGuestListening();
      };
      session.onend = () => {
        if (recognition !== session) return;
        listening = false;
        clearTimeout(listeningTimeout);
        listeningTimeout = null;
        microphone.textContent = 'Speak your question';
        microphone.setAttribute('aria-pressed', 'false');
        if (!receivedSpeech && !voiceFailed && voiceStatus.textContent === 'Listening… Speak your question.') {
          voiceStatus.textContent = 'No question captured. Try again or type your question.';
        }
      };
      listening = true;
      microphone.textContent = 'Stop microphone';
      microphone.setAttribute('aria-pressed', 'true');
      voiceStatus.textContent = 'Waiting for microphone access…';
      session.onstart = () => {
        if (recognition === session && listening) voiceStatus.textContent = 'Listening… Speak your question.';
      };
      session.start();
      listeningTimeout = setTimeout(() => {
        if (recognition !== session || !listening) return;
        stopGuestListening();
        voiceStatus.textContent = receivedSpeech
          ? 'Words captured. Review your question and select Find my wine.'
          : 'No words came through. Try Safari directly or use the iPhone keyboard microphone in the question field.';
      }, 20000);
    } catch (_) {
      listening = false;
      clearTimeout(listeningTimeout);
      listeningTimeout = null;
      microphone.textContent = 'Speak your question';
      microphone.setAttribute('aria-pressed', 'false');
      voiceStatus.textContent = 'Speech recognition is unavailable here. You can type your question.';
    }
  });
}
// iOS permission prompts can temporarily hide the document. Stop only on actual navigation.
window.addEventListener('pagehide', stopGuestListening);
