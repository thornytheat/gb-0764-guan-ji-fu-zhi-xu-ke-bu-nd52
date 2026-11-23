const note = document.querySelector('#note');

async function send(address, body) {
  const reply = await fetch(address, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
  });
  const data = await reply.json();
  if (!reply.ok) throw new Error(data.message || '无法保存卷宗');
  return data;
}

function bind(form, work) {
  form?.addEventListener('submit', async event => {
    event.preventDefault();
    const trigger = form.querySelector('button');
    trigger.disabled = true;
    note.textContent = '正在核对卷宗…';
    try { await work(form); }
    catch (error) { note.textContent = error.message; }
    finally { trigger.disabled = false; }
  });
}

const sample = document.querySelector('#sample');

bind(document.querySelector('#deposit'), async form => {
  const csv = document.querySelector('#rows').value;
  const result = await send('/api/volumes', csv ? {csv} : {sample:form.dataset.sample});
  location.assign('/folio/stamp?' + new URLSearchParams({run:result.run_id, sample:form.dataset.sample}));
});

const select = document.querySelector('#volume');
const output = document.querySelector('#imprint-value');
const file = document.querySelector('#certificate');
const mark = document.querySelector('#paper-stamp');
select?.addEventListener('change', () => {
  if (output) output.value = '';
  if (file) file.hidden = true;
  mark.textContent = '待盖印';
});
bind(document.querySelector('#stamp'), async () => {
  const selected = select.value;
  const record = await send(`/api/volumes/${selected}/stamp`, {});
  if (select.value !== selected) return;
  output.value = record.imprint;
  file.href = `/api/volumes/${selected}/export`;
  file.hidden = false;
  mark.textContent = '已签发';
  note.textContent = record.reused ? '已取回原凭证' : '复制许可凭证已落印';
  if (!document.querySelector('.dispatch')) {
    location.assign('/folio/stamp?' + new URLSearchParams({run:selected, sample:sample ? sample.value : 'dirty'}));
  }
});
document.querySelector('#print-slip')?.addEventListener('click', () => window.print());

function compose(text) {
  return text.split('\n').map(line => line.trim()).filter(Boolean).map(line => {
    const [entry, pages] = line.split(/,|，|\t/).map(part => part.trim());
    if (!entry || !pages) throw new Error('每行请填写「订单,页段」');
    return {entry, pages};
  });
}

async function record(form, endpoint, identity, day, lines, message) {
  const run = form.closest('.dispatch').dataset.run;
  const result = await send(`/api/volumes/${run}/${endpoint}`, {
    [identity]: form.querySelector(`[name=${identity}]`).value.trim(),
    [day]: form.querySelector(`[name=${day}]`).value,
    lines: compose(form.querySelector(`[name=${lines}]`).value),
  });
  sessionStorage.setItem('dispatch-note', result.reused
    ? `${result[identity]} 早已登记，内容一致。${message(result)}`
    : `${result[identity]} 已登记。${message(result)}`);
  location.reload();
}

const flash = sessionStorage.getItem('dispatch-note');
if (flash) {
  note.textContent = flash;
  sessionStorage.removeItem('dispatch-note');
}

bind(document.querySelector('#dispatch'), form => record(form, 'dispatch', 'batch', 'sent_on', 'batch-lines',
  result => `寄送 ${result.summary.dispatched} 页；可补寄 ${result.summary.resend} 页，等回执 ${result.summary.awaiting} 页。`));
bind(document.querySelector('#receipt'), form => record(form, 'receipt', 'receipt', 'received_on', 'receipt-lines',
  result => `实收 ${result.summary.received} 页；未结清 ${result.summary.outstanding} 页，待核查 ${result.summary.review} 页。`));
