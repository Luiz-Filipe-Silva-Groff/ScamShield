const $ = id => document.getElementById(id);
let documentData = null;
let busy = false;

function toBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.readAsDataURL(blob);
  });
}
function error(message) { $('error').textContent = message; }
function clearResult() { $('result').hidden = true; $('empty').hidden = false; $('json').textContent = ''; }
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
  $('selected').classList.add('file-ready');
  $('selected').textContent = `Arquivo carregado: ${file.name || 'boleto.pdf'} (${Math.max(1, Math.ceil(file.size / 1024))} KB). Clique em “Analisar boleto” para conferir.`;
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
    $('key').value = 'scamshield-demo-local';
    $('demo-section').hidden = false;
    $('demo-upload-note').hidden = false;
    const cases = await (await fetch('/demo/cases')).json();
    for (const item of cases) {
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
