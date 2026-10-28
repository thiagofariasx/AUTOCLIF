const SPREADSHEET_ID = '1hlQx9xTAIiQYwNzUG8qDIZNkGM_Ts0t0DGwkEBznXIs';
const GVIZ_FORMULAS = `https://docs.google.com/spreadsheets/d/${SPREADSHEET_ID}/gviz/tq?tqx=out:json&sheet=FORMULAS`;
const APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbw-bXcPWmDXLZOz6_x30gFGMjI0A1vrMhc4_opah8kJMY1zQNVktnaQkve5GXYhbc1Z/exec';

let lineChart, barChart, pieChart;
let returnTimer = null;
let secondsRemaining = 120;

let isFetching = false;
let isChangingDate = false;

function localToday() {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function numericVolume(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  let text = String(value).replace(/\s/g, '');
  if (text.includes(',')) text = text.replace(/\./g, '').replace(',', '.');
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function updateAttendancePercent() {
  const scheduled = numericVolume(document.getElementById('kpiAgendados').innerText);
  const attended = numericVolume(document.getElementById('kpiConcluidos').innerText);
  const valid = scheduled !== null && scheduled > 0 && attended !== null && attended >= 0;
  const ratio = valid ? (attended / scheduled) * 100 : null;
  const label = ratio === null ? '—' : `${ratio.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}%`;
  
  const percentEl = document.getElementById('attendancePercent');
  const arcEl = document.getElementById('attendanceArc');
  const ringEl = document.getElementById('attendanceRing');

  if (percentEl) percentEl.innerText = label;
  if (arcEl) arcEl.style.strokeDasharray = `${ratio === null ? 0 : Math.min(100, ratio)} 100`;
  if (ringEl) ringEl.setAttribute('aria-label', valid ? `Atendidos em relação aos agendados: ${label}. ${attended} atendidos e ${scheduled} agendados.` : 'Percentual indisponível: sem base válida de agendamentos.');
}

function setLoading(value) {
  const picker = document.getElementById('datePicker');
  const btnToday = document.getElementById('btnToday');
  if (picker) picker.disabled = value;
  if (btnToday) btnToday.disabled = value;
  const mainEl = document.querySelector('main');
  if (mainEl) mainEl.setAttribute('aria-busy', String(value));
}

async function changeConsultationDate(date) {
  if (isFetching || isChangingDate) return;
  isChangingDate = true;
  setLoading(true);
  const lastUpdate = document.getElementById('lastUpdate');
  if (lastUpdate) lastUpdate.innerText = 'Atualizando data de consulta…';
  try {
    await updateSheetDate(formatDateToBR(date));
    await fetchData(true);
  } catch (error) {
    console.error('Erro ao alterar a consulta:', error);
    if (lastUpdate) lastUpdate.innerText = 'Falha na consulta · os valores exibidos são da última atualização confirmada';
  } finally { 
    isChangingDate = false; 
    setLoading(false); 
  }
}

Chart.register(ChartDataLabels);

function getAdaptiveFontSize(context, baseFactor = 0.04, minSize = 10, maxSize = 18) {
  const chart = context.chart;
  const width = chart.width || 300;
  const height = chart.height || 200;
  const dim = Math.min(width, height);
  const calculated = Math.round(dim * baseFactor);
  return Math.max(minSize, Math.min(maxSize, calculated));
}

// Cores do ranking de produtividade
const COR_PODIO = { 1: '#fbbf24', 2: '#cbd5e1', 3: '#cd7f32' };   // 1º ouro, 2º prata, 3º bronze
const COR_BARRA_PADRAO = '#2563eb';                                // 4º em diante
const COR_PODIO_CLARAS = ['#fbbf24', '#cbd5e1'];                   // fundos claros: número escuro para dar leitura

const crownPlugin = {
  id: 'crownPlugin',
  afterDraw: (chart) => {
    if (chart.config.type !== 'bar') return;
    const ctx = chart.ctx;
    const dataset = chart.data.datasets[0];
    if (!dataset || !dataset.data.length) return;

    const maxVal = Math.max(...dataset.data);
    if (maxVal <= 0) return;

    const maxIndex = dataset.data.indexOf(maxVal);
    const meta = chart.getDatasetMeta(0);
    const bar = meta.data[maxIndex];

    if (bar) {
      ctx.save();
      const fontSize = getAdaptiveFontSize({ chart }, 0.065, 14, 22);
      ctx.font = `${fontSize}px sans-serif`;
      ctx.textAlign = 'center';
      const yPos = Math.max(bar.y - 6, fontSize);
      ctx.fillText('👑', bar.x, yPos);
      ctx.restore();
    }
  }
};

Chart.register(crownPlugin);

document.addEventListener('DOMContentLoaded', () => {
  initDatePicker();
  initCharts();
  fetchData();
  setInterval(fetchData, 30000);

  window.addEventListener('resize', () => {
    if (lineChart) lineChart.resize();
    if (barChart) barChart.resize();
    if (pieChart) pieChart.resize();
  });
});

function parseDateValue(val) {
  if (!val) return '';
  if (typeof val === 'string' && val.startsWith('Date(')) {
    const parts = val.replace('Date(', '').replace(')', '').split(',').map(Number);
    if (parts.length >= 3) {
      const year = parts[0];
      const month = String(parts[1] + 1).padStart(2, '0');
      const day = String(parts[2]).padStart(2, '0');
      return `${day}/${month}/${year}`;
    }
  }
  return String(val);
}

function parseTimeValue(val) {
  if (!val) return '00:00:00';
  if (typeof val === 'string' && val.startsWith('Date(')) {
    const parts = val.replace('Date(', '').replace(')', '').split(',').map(Number);
    if (parts.length >= 6) {
      const h = String(parts[3]).padStart(2, '0');
      const m = String(parts[4]).padStart(2, '0');
      const s = String(parts[5]).padStart(2, '0');
      return `${h}:${m}:${s}`;
    }
  }
  return String(val);
}

function initDatePicker() {
  const datePicker = document.getElementById('datePicker');
  const btnToday = document.getElementById('btnToday');
  const todayStr = localToday();
  
  if (datePicker) {
    datePicker.value = todayStr;
    datePicker.addEventListener('change', () => {
      if (!datePicker.value) { datePicker.value = localToday(); return; }
      if (datePicker.value !== localToday()) startReturnTimer();
      else { 
        clearInterval(returnTimer); 
        const timerElem = document.getElementById('status-timer');
        if (timerElem) timerElem.classList.add('hidden'); 
      }
      changeConsultationDate(datePicker.value);
    });
  }
  if (btnToday) btnToday.addEventListener('click', resetToToday);
}

function formatDateToBR(dateStringStr) {
  if (!dateStringStr) return '';
  const [year, month, day] = dateStringStr.split('-');
  return `${day}/${month}/${year}`;
}

async function updateSheetDate(formattedDateBR) {
  const res = await fetch(`${APPS_SCRIPT_URL}?data=${encodeURIComponent(formattedDateBR)}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Falha HTTP ${res.status}`);
  const json = await res.json();
  if (numericVolume(json?.b2) === null) throw new Error('Resposta inválida ao alterar data');
}

function startReturnTimer() {
  clearInterval(returnTimer);
  secondsRemaining = 120;
  const timerElem = document.getElementById('status-timer');
  const secElem = document.getElementById('timer-seconds');
  
  if (timerElem) timerElem.classList.remove('hidden');
  if (secElem) secElem.innerText = secondsRemaining;

  returnTimer = setInterval(() => {
    if (isFetching || isChangingDate) return;
    secondsRemaining--;
    if (secElem) secElem.innerText = secondsRemaining;
    if (secondsRemaining <= 0) {
      resetToToday();
    }
  }, 1000);
}

function resetToToday() {
  clearInterval(returnTimer);
  const timerElem = document.getElementById('status-timer');
  const datePicker = document.getElementById('datePicker');
  if (timerElem) timerElem.classList.add('hidden');
  if (datePicker) datePicker.value = localToday();
  return changeConsultationDate(localToday());
}

function initCharts() {
  const ctxLine = document.getElementById('chartAgendadoXAtendido').getContext('2d');
  
  const gradBlue = ctxLine.createLinearGradient(0, 0, 0, 300);
  gradBlue.addColorStop(0, 'rgba(59, 130, 246, 0.3)');
  gradBlue.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

  const gradGreen = ctxLine.createLinearGradient(0, 0, 0, 300);
  gradGreen.addColorStop(0, 'rgba(16, 185, 129, 0.3)');
  gradGreen.addColorStop(1, 'rgba(16, 185, 129, 0.0)');

  lineChart = new Chart(ctxLine, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { 
          label: 'Agendados', data: [], borderColor: '#3b82f6', backgroundColor: gradBlue, fill: true, tension: 0.35, 
          pointRadius: 5, pointHoverRadius: 7, pointBackgroundColor: '#3b82f6', pointBorderColor: '#ffffff', pointBorderWidth: 2, clip: false,
          datalabels: { align: 'top', anchor: 'end', color: '#60a5fa', backgroundColor: 'rgba(15, 23, 42, 0.85)', borderRadius: 4, padding: { top: 2, bottom: 2, left: 5, right: 5 } }
        },
        { 
          label: 'Atendidos', data: [], borderColor: '#10b981', backgroundColor: gradGreen, fill: true, tension: 0.35, 
          pointRadius: 5, pointHoverRadius: 7, pointBackgroundColor: '#10b981', pointBorderColor: '#ffffff', pointBorderWidth: 2, clip: false,
          datalabels: { align: 'bottom', anchor: 'start', color: '#34d399', backgroundColor: 'rgba(15, 23, 42, 0.85)', borderRadius: 4, padding: { top: 2, bottom: 2, left: 5, right: 5 } }
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { top: 25, bottom: 10, left: 15, right: 15 } },
      plugins: {
        legend: { labels: { color: '#94a3b8', font: { size: 11, weight: 'bold' }, usePointStyle: true } },
        datalabels: { font: (context) => ({ weight: '900', size: getAdaptiveFontSize(context, 0.038, 11, 15) }) }
      },
      scales: {
        x: { ticks: { autoSkip: false, color: '#94a3b8', font: { size: 10, weight: 'bold' } }, grid: { color: '#1e293b' } },
        y: { grace: '18%', ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#1e293b' } }
      }
    }
  });

  const ctxBar = document.getElementById('chartProdutividade').getContext('2d');
  barChart = new Chart(ctxBar, {
    type: 'bar',
    data: { labels: [], datasets: [{ label: 'Atendimentos', data: [], backgroundColor: '#2563eb', borderRadius: 6, borderSkipped: false, clip: false }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { top: 22, bottom: 0 } },
      plugins: {
        legend: { display: false },
        datalabels: {
          color: (context) => {
            const bg = context.dataset.backgroundColor;
            const cor = Array.isArray(bg) ? bg[context.dataIndex] : bg;
            return COR_PODIO_CLARAS.includes(cor) ? '#0b1120' : '#ffffff';
          },
          anchor: 'center', align: 'center', font: (context) => ({ weight: '900', size: getAdaptiveFontSize(context, 0.045, 11, 18) }) }
      },
      scales: {
        x: { ticks: { autoSkip: false, minRotation: 0, maxRotation: 0, color: '#ffffff', font: { size: 11, weight: 'bold' } }, grid: { display: false } },
        y: { grace: '25%', ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#1e293b' } }
      }
    }
  });

  const ctxPie = document.getElementById('chartTipos').getContext('2d');
  pieChart = new Chart(ctxPie, {
    type: 'pie',
    data: { labels: [], datasets: [{ data: [], backgroundColor: ['#0284c7', '#3b82f6', '#f59e0b', '#ec4899', '#10b981'], borderWidth: 2, borderColor: '#0b1120', clip: false }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      layout: { padding: 12 },
      plugins: {
        legend: { position: 'bottom', labels: { color: '#cbd5e1', font: { size: 9, weight: 'bold' }, padding: 8, usePointStyle: true } },
        datalabels: {
          color: '#ffffff',
          font: (context) => ({ weight: '900', size: getAdaptiveFontSize(context, 0.045, 10, 16) }),
          formatter: (value, ctx) => {
            let sum = ctx.dataset.data.reduce((a, b) => a + b, 0);
            if (sum === 0) return '0\n(0%)';
            let percentage = ((value * 100) / sum).toFixed(1) + "%";
            return `${value}\n(${percentage})`;
          }
        }
      }
    }
  });
}

async function fetchData(force = false) {
  if (isFetching || (isChangingDate && !force)) return;
  isFetching = true;
  setLoading(true);
  try {
    const results = await Promise.allSettled([
      fetch(APPS_SCRIPT_URL, { cache: 'no-store' }).then(async response => { if (!response.ok) throw new Error(`Falha HTTP ${response.status}`); return response.json(); }),
      fetch(GVIZ_FORMULAS, { cache: 'no-store' }).then(async response => { if (!response.ok) throw new Error(`Falha HTTP ${response.status}`); return response.text(); })
    ]);
    const failure = results.find(result => result.status === 'rejected');
    if (failure) throw failure.reason;
    
    const jsonB2 = results[0].value;
    const textFormulas = results[1].value;
    
    const wrapped = textFormulas.match(/google\.visualization\.Query\.setResponse\(([\s\S]*)\);?\s*$/);
    const jsonFormulas = JSON.parse(wrapped ? wrapped[1] : textFormulas);
    const rows = jsonFormulas.table?.rows;
    if (!Array.isArray(rows)) throw new Error('Consulta inválida');
    
    const kpiAgendados = document.getElementById('kpiAgendados');
    if (kpiAgendados) kpiAgendados.innerText = String(jsonB2.b2 ?? '0');

    const kpiConcluidos = document.getElementById('kpiConcluidos');
    const kpiFila = document.getElementById('kpiFila');
    if (kpiConcluidos) kpiConcluidos.innerText = getDirectVal(rows, 1, 7) || '0'; // H2
    if (kpiFila) kpiFila.innerText = getDirectVal(rows, 2, 7) || '0';       // H3

    updateAttendancePercent();

    const mediaEsperaDia = document.getElementById('mediaEsperaDia');
    const mediaGuicheDia = document.getElementById('mediaGuicheDia');
    const mediaEsperaGeral = document.getElementById('mediaEsperaGeral');
    const mediaAtendimentoGeral = document.getElementById('mediaAtendimentoGeral');
    const mediaGeral = document.getElementById('mediaGeral');

    if (mediaEsperaDia) mediaEsperaDia.innerText = parseTimeValue(getRawVal(rows, 1, 15)); // P2
    if (mediaGuicheDia) mediaGuicheDia.innerText = parseTimeValue(getRawVal(rows, 1, 16)); // Q2
    if (mediaEsperaGeral) mediaEsperaGeral.innerText = parseTimeValue(getRawVal(rows, 1, 18)); // S2
    if (mediaAtendimentoGeral) mediaAtendimentoGeral.innerText = parseTimeValue(getRawVal(rows, 1, 19)); // T2
    if (mediaGeral) mediaGeral.innerText = parseTimeValue(getRawVal(rows, 1, 20)); // U2

    const lineLabels = [];
    const agendados = [];
    const atendidos = [];
    for (let i = 1; i <= 5; i++) {
      const rawDate = getRawVal(rows, i, 3); // D
      if (rawDate) {
        lineLabels.push(parseDateValue(rawDate));
        agendados.push(parseFloat(getDirectVal(rows, i, 4)) || 0); // E
        atendidos.push(parseFloat(getDirectVal(rows, i, 13)) || 0); // N
      }
    }
    lineChart.data.labels = lineLabels;
    lineChart.data.datasets[0].data = agendados;
    lineChart.data.datasets[1].data = atendidos;
    lineChart.update();

    // Ranking sempre do 1º ao último (maior para menor); empate no valor divide a mesma posição
    const ranking = [];
    for (let i = 1; i < rows.length; i++) {
      const atendente = getDirectVal(rows, i, 9); // J
      const qtd = parseFloat(getDirectVal(rows, i, 10)); // K
      if (atendente && !isNaN(qtd)) ranking.push({ nome: atendente, qtd });
    }
    ranking.sort((a, b) => (b.qtd - a.qtd) || String(a.nome).localeCompare(String(b.nome), 'pt-BR'));

    const barLabels = ranking.map(r => r.nome);
    const barData = ranking.map(r => r.qtd);
    const bgColors = ranking.map(r => {
      if (r.qtd <= 0) return COR_BARRA_PADRAO;                         // sem atendimento não ganha medalha
      const posicao = ranking.findIndex(x => x.qtd === r.qtd) + 1;      // 1, 2, 3... (empate = mesma posição)
      return COR_PODIO[posicao] || COR_BARRA_PADRAO;
    });
    barChart.data.labels = barLabels;
    barChart.data.datasets[0].data = barData;
    barChart.data.datasets[0].backgroundColor = bgColors;
    barChart.update();

    const pieLabels = [];
    const pieData = [];
    for (let i = 1; i < rows.length; i++) {
      const tipo = getDirectVal(rows, i, 22); // W
      const qtd = parseFloat(getDirectVal(rows, i, 23)); // X
      if (tipo && !isNaN(qtd)) {
        pieLabels.push(tipo);
        pieData.push(qtd);
      }
    }
    pieChart.data.labels = pieLabels;
    pieChart.data.datasets[0].data = pieData;
    pieChart.update();

    const lastUpdateElem = document.getElementById('lastUpdate');
    if (lastUpdateElem) {
      lastUpdateElem.innerHTML = `
        <span class="inline-flex items-center gap-1.5">
          <span class="relative flex h-2 w-2">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <strong class="text-emerald-400 font-bold tracking-wider uppercase">AO VIVO</strong>
          <span class="text-slate-600">•</span>
          <span>Última Atualização: ${new Date().toLocaleTimeString('pt-BR')}</span>
        </span>
      `;
    }

  } catch (err) {
    console.error('Erro ao atualizar dados:', err);
    const lastUpdateElem = document.getElementById('lastUpdate');
    if (lastUpdateElem) lastUpdateElem.innerText = 'Falha na atualização · exibindo os últimos dados confirmados';
  } finally { 
    isFetching = false; 
    if (!isChangingDate) setLoading(false); 
  }
}

function getDirectVal(rows, rowIndex, colIndex) {
  try {
    if (!rows[rowIndex] || !rows[rowIndex].c || !rows[rowIndex].c[colIndex]) return null;
    const cell = rows[rowIndex].c[colIndex];
    if (cell.f !== undefined && cell.f !== null) return cell.f;
    if (cell.v !== undefined && cell.v !== null) return cell.v;
    return null;
  } catch (e) {
    return null;
  }
}

function getRawVal(rows, rowIndex, colIndex) {
  try {
    if (!rows[rowIndex] || !rows[rowIndex].c || !rows[rowIndex].c[colIndex]) return null;
    return rows[rowIndex].c[colIndex].v;
  } catch (e) {
    return null;
  }
}