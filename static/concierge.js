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
  } finally { clearTimeout(timeout); submit.disabled = false; }
});


// Optional browser voice features. Typed questions remain available everywhere.
const micButton = document.getElementById('mic-button');
const speakToggle = document.getElementById('speak-toggle');
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;
if (micButton) {
  micButton.hidden = false;
  micButton.addEventListener('click', () => {
    if (!SpeechRecognition) {
      promptInput.focus();
      statusLine.textContent = 'Voice recognition is not supported in this browser. On iPhone, tap the microphone on your keyboard to dictate your question, then tap Find my wine.';
      return;
    }
    if (listening) { recognition.stop(); return; }
    recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onstart = () => { listening = true; micButton.textContent = 'Stop listening'; micButton.setAttribute('aria-pressed', 'true'); statusLine.textContent = 'Listening for your question…'; };
    recognition.onresult = event => { promptInput.value = event.results[0][0].transcript; statusLine.textContent = 'Question captured. Tap Find my wine to continue.'; promptInput.focus(); };
    recognition.onerror = event => { statusLine.textContent = event.error === 'not-allowed' ? 'Microphone access was denied. Please enable it in browser settings or type your question.' : 'Voice input was unavailable. You can type your question instead.'; };
    recognition.onend = () => { listening = false; micButton.textContent = '🎙 Speak your question'; micButton.setAttribute('aria-pressed', 'false'); };
    try { recognition.start(); } catch (_) { statusLine.textContent = 'Voice input could not start. Please type your question.'; }
  });
}
if (speakToggle && 'speechSynthesis' in window) {
  speakToggle.hidden = false;
  speakToggle.addEventListener('click', () => {
    if (window.speechSynthesis.speaking) { window.speechSynthesis.cancel(); return; }
    const answer = document.getElementById('answer').textContent.trim();
    if (!answer) return;
    const utterance = new SpeechSynthesisUtterance(answer);
    utterance.lang = 'en-US'; utterance.rate = 0.95;
    window.speechSynthesis.speak(utterance);
  });
}
