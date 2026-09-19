const $ = id => document.getElementById(id);
let documentData = null;
let busy = false;
const demoCasesByFile = new Map();

function toBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.readAsDataURL(blob);
  });
}
function error(message) { $('error').textContent = message; }
function clearResult() {
  $('result').hidden = true; $('unknown').hidden = true; $('empty').hidden = false;
  $('json').textContent = ''; $('unknown-json').textContent = '';
}
function resetSelection() {
  documentData = null;
  $('selected').classList.remove('file-ready');
  $('selected').textContent = 'Nenhum documento selecionado.';
  $('file-label').textContent = 'Selecionar boleto';
}
function setBusy(value) {
  busy = value;
  document.querySelectorAll('button,input,textarea').forEach(node => { node.disabled = value; });
  $('analyze').textContent = value ? 'Conferindo as informações…' : 'Analisar boleto →';
}
async function chooseFile(file) {
  resetSelection();
  clearResult(); error('');
  if (!file || file.size > 5 * 1024 * 1024) { error('Selecione um arquivo com até 5 MiB.'); return; }
  if (!['application/pdf', 'image/jpeg', 'image/png'].includes(file.type)) { error('Use um PDF, JPG ou PNG.'); return; }
  documentData = { mime_type: file.type, base64: await toBase64(file) };
  const demoCase = demoCasesByFile.get(file.name.toLowerCase());
  if (demoCase) $('line').value = demoCase.line;
  $('selected').classList.add('file-ready');
  const demoMessage = demoCase ? ` Código de teste preenchido para “${demoCase.label}”.` : '';
  $('selected').textContent = `Arquivo carregado: ${file.name || 'boleto.pdf'} (${Math.max(1, Math.ceil(file.size / 1024))} KB).${demoMessage} Clique em “Analisar boleto” para conferir.`;
  $('file-label').textContent = 'Trocar boleto';
}
$('file').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  if (document.querySelector('.case.active')) $('line').value = '';
  document.querySelectorAll('.case').forEach(node => node.classList.remove('active'));
  setBusy(true);
  try { await chooseFile(file); } catch { error('Não foi possível ler o arquivo.'); }
  finally { setBusy(false); }
});
$('clear').addEventListener('click', () => {
  resetSelection(); $('file').value = ''; $('line').value = '';
  error(''); clearResult();
  document.querySelectorAll('.case').forEach(node => node.classList.remove('active'));
});
$('analyze').addEventListener('click', async () => {
  if (busy) return;
  error(''); clearResult();
  if (!documentData && !$('line').value.trim()) { error('Selecione um documento ou informe o código de pagamento.'); return; }
  if (!$('key').value) { error('Informe a chave de acesso do parceiro.'); return; }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  const started = performance.now();
  setBusy(true);
  try {
    const request = {};
    if (documentData) request.documento = documentData;
    if ($('line').value.trim()) request.linha_digitavel = $('line').value.trim();
    const response = await fetch('/v1/analise', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': $('key').value }, body: JSON.stringify(request), signal: controller.signal });
    const result = await response.json();
    if (!response.ok) { error(result.message || 'Não foi possível concluir a análise.'); return; }
    // Arquivo fora do catálogo da demo devolve WARNING/10 como qualquer documento
    // ilegível. Mostrado como score, parece veredito de risco sobre o boleto de
    // quem testou; o que houve foi a demo não reconhecer o arquivo.
    if (result.details.signals.some(signal => signal.code === 'DOCUMENT_UNKNOWN_DEMO_DOCUMENT')) {
      $('empty').hidden = true; $('unknown').hidden = false;
      $('unknown-json').textContent = JSON.stringify(result, null, 2);
      $('unknown-request-id').textContent = 'ID da análise: ' + result.request_id;
      return;
    }
    $('empty').hidden = true; $('result').hidden = false; $('result').className = result.status;
    $('status').textContent = result.status; $('title').textContent = result.title;
    $('explanation').textContent = result.explanation; $('score').textContent = result.score;
    $('score-bar').style.width = result.score + '%';
    $('latency').textContent = ((performance.now() - started) / 1000).toFixed(2) + ' s';
    $('signals').replaceChildren();
    for (const signal of result.details.signals) {
      const li = document.createElement('li');
      const marker = document.createElement('span'); marker.className = 'signal-marker ' + signal.outcome;
      marker.textContent = signal.outcome === 'pass' ? '✓' : '!';
      const text = document.createElement('span'); text.textContent = signal.explanation;
      li.append(marker, text); $('signals').append(li);
    }
    $('json').textContent = JSON.stringify(result, null, 2);
    $('request-id').textContent = 'ID da análise: ' + result.request_id;
  } catch { error('Não foi possível conectar ao serviço ou a requisição demorou demais.'); }
  finally { clearTimeout(timer); setBusy(false); }
});
async function initialize() {
  try {
    const health = await (await fetch('/health')).json();
    $('mode').textContent = health.mode === 'demo' ? 'Demonstração sem rede' : 'Integrações reais';
    if (health.mode !== 'demo') {
      $('privacy').textContent = 'O serviço processa o arquivo em memória e o envia ao provedor de leitura configurado. A retenção externa segue os termos desse provedor.';
      return;
    }
    // A chave vem do servidor: fixá-la aqui quebraria a página em qualquer
    // instância que configure um parceiro próprio.
    const access = await (await fetch('/demo/access')).json();
    $('key').value = access.key;
    $('key').type = 'text';
    $('key-note').hidden = false;
    $('demo-section').hidden = false;
    $('demo-upload-note').hidden = false;
    const cases = await (await fetch('/demo/cases')).json();
    for (const item of cases) demoCasesByFile.set(item.file.toLowerCase(), item);
    $('downloads-summary').textContent = `Baixar os boletos de teste (${cases.length} PDFs)`;
    $('downloads').hidden = false;
    for (const item of cases) {
      const li = document.createElement('li');
      const row = document.createElement('div'); row.className = 'dl-row';
      const link = document.createElement('a');
      link.href = '/demo/files/' + encodeURIComponent(item.id);
      link.setAttribute('download', '');
      link.textContent = '⤓ ' + item.label;
      const expected = document.createElement('span');
      expected.textContent = `${item.expected_status} · ${item.expected_score}`;
      row.append(link, expected);
      li.append(row); $('download-list').append(li);
      const button = document.createElement('button'); button.className = 'case'; button.textContent = item.label;
      button.addEventListener('click', async () => {
        setBusy(true);
        try {
          const response = await fetch('/demo/files/' + encodeURIComponent(item.id));
          if (!response.ok) throw new Error();
          $('file').value = '';
          await chooseFile(new File([await response.blob()], item.label + '.pdf', { type: 'application/pdf' }));
          $('line').value = item.line;
          document.querySelectorAll('.case').forEach(node => node.classList.remove('active'));
          button.classList.add('active');
        } catch { error('Não foi possível carregar o cenário.'); }
        finally { setBusy(false); }
      });
      $('cases').append(button);
    }
  } catch { $('mode').textContent = 'Serviço indisponível'; }
}
initialize();
