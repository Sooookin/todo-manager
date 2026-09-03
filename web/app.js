const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const api = (u, b) => fetch(u, b ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(b)} : undefined).then(r => r.json());
const WD = ['월','화','수','목','금','토','일'];
const esc = s => (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const mins = t => +t.slice(0,2)*60 + +t.slice(3);

/* 시각은 모두 5분 단위. 키보드로 직접 입력할 수 있고(09:30, 0930),
   5분 배수가 아닌 값이 들어오면 가장 가까운 5분으로 맞춘다. */
const STEP = 5;
const pad2 = n => String(n).padStart(2, '0');
const hhmm = m => pad2(Math.floor(m/60)) + ':' + pad2(m%60);
function snapTime(el){
  if(!el.value || !/^\d\d:\d\d/.test(el.value)) return;
  el.value = hhmm(Math.min(1435, Math.max(0, Math.round(mins(el.value)/STEP)*STEP)));
}
/* 폼은 그때그때 새로 그리므로 개별 바인딩 대신 문서 한 곳에서 위임 처리한다. */
document.addEventListener('change', e => {
  const el = e.target;
  if(!el.matches) return;
  if(el.matches('input[type="time"]')) snapTime(el);
  else if(el.matches('input.min5') && el.value !== '')
    el.value = Math.max(0, Math.round(+el.value/STEP)*STEP);
}, true);
let STATE = null, HOL = new Set();

const say = m => { $('#status').textContent = m; clearTimeout(say._t); say._t = setTimeout(()=>$('#status').textContent='', 2800); };

/* ══════════ 창 버튼 ══════════ */
function wireWindow(){
  const has = () => window.pywebview && window.pywebview.api;
  $('#w-min').onclick = () => has() && window.pywebview.api.minimize();
  $('#w-max').onclick = () => has() && window.pywebview.api.toggle_max();
  $('#w-close').onclick = () => has() ? window.pywebview.api.close() : window.close();
}
wireWindow();
window.addEventListener('pywebviewready', wireWindow);

/* ══════════ 날짜 · 영업일 ══════════ */
const iso = d => new Date(d.getTime() - d.getTimezoneOffset()*60000).toISOString().slice(0,10);
const dObj = s => new Date(s+'T12:00');
const bizOn = () => STATE.settings.business_only !== false;
function isBiz(s){ const w = dObj(s).getDay(); return w>=1 && w<=5 && !HOL.has(s); }
function rollBiz(s, dir){
  if(!bizOn()) return s;
  let d = dObj(s);
  for(let i=0; i<40 && !isBiz(iso(d)); i++) d.setDate(d.getDate() + (dir||1));
  return iso(d);
}
function shift(days){ const d = dObj(STATE.today); d.setDate(d.getDate()+days); return rollBiz(iso(d), 1); }
function nextWd(w){ const d = dObj(STATE.today); let k = (w+1 - d.getDay() + 7) % 7; d.setDate(d.getDate() + (k||7)); return rollBiz(iso(d), 1); }
function fmtDay(s){
  if(!s) return '';
  const diff = Math.round((dObj(s) - dObj(STATE.today))/864e5);
  if(diff===0) return '오늘';
  if(diff===1) return '내일';
  if(diff===2) return '모레';
  if(diff===-1) return '어제';
  if(diff<0) return (-diff)+'일 지남';
  const d = dObj(s);
  return (d.getMonth()+1)+'/'+d.getDate()+' ('+WD[(d.getDay()+6)%7]+')';
}

/* ══════════ 항목 행 ══════════ */
function itemEl(i, opt){
  opt = opt || {};
  const el = document.createElement('div');
  el.className = 'item k-' + (i.kind || 'deadline') + (i.done ? ' done' : '');
  const bits = [];
  const overdue = opt.showOverdue && i.date && i.date < STATE.today;
  if(overdue) bits.push('<span class="late">'+fmtDay(i.date)+(i.time ? ' '+i.time : '')+'</span>');
  else if(opt.showDate && i.date) bits.push('<span class="pill">'+fmtDay(i.date)+'</span>');
  if(i.time && !overdue){
    let cls = '';
    if(i.date === STATE.today && !i.done)
      cls = i.time < STATE.now ? 'late' : (mins(i.time) - mins(STATE.now) <= 90 ? 'soon' : '');
    bits.push('<span class="'+cls+'">'+i.time+(cls==='late' ? ' 지남' : ' 까지')+'</span>');
  }
  if(i.kind === 'routine') bits.push('<span title="'+esc(i.rule_text)+'">↻</span>');
  if(i.muted) bits.push('<span>알림 끔</span>');
  if(i.note) bits.push('<span>· '+esc(i.note.slice(0,22))+'</span>');
  el.innerHTML = '<div class="dot" title="완료"></div>'+
    '<div class="body"><div class="t">'+esc(i.title)+'</div>'+
    (bits.length ? '<div class="meta">'+bits.join('')+'</div>' : '')+'</div>'+
    '<button class="rowbtn" title="수정 / 삭제">✎</button>';
  el.querySelector('.dot').onclick = () => api('/api/task/'+i.id+'/toggle', {date:i.date}).then(load);
  el.querySelector('.body').onclick = () => openEdit(i);
  el.querySelector('.rowbtn').onclick = () => openEdit(i);
  return el;
}

/* 반복 업무 행: 완료 체크 없이 "다음 예정일"만 */
function routineEl(i){
  const el = document.createElement('div');
  const isToday = i.next_date === STATE.today;
  el.className = 'item rt k-routine' + (isToday ? (i.done ? ' cleared' : ' today') : '');
  const when = i.next_date ? fmtDay(i.next_date) + (i.time ? ' '+i.time : '') : '예정 없음';
  el.innerHTML = '<div class="body"><div class="t">'+esc(i.title)+'</div>'+
    '<div class="meta"><span class="pill">↻ '+esc(i.rule_text)+'</span>'+
    (i.muted ? '<span class="pill">알림 끔</span>' : '')+
    (isToday && i.done ? '<span>오늘 완료</span>' : '')+'</div></div>'+
    '<span class="when">'+when+'</span>'+
    '<button class="rowbtn" title="수정 / 삭제">✎</button>';
  el.querySelector('.body').onclick = () => openEdit(i);
  el.querySelector('.rowbtn').onclick = () => openEdit(i);
  return el;
}

function fill(node, list, emptyMsg, opt, maker){
  node.innerHTML = '';
  if(!list.length){ node.innerHTML = '<div class="empty">'+emptyMsg+'</div>'; return; }
  list.forEach(i => node.appendChild((maker||itemEl)(i, opt)));
}

function render(o){
  STATE = o;
  HOL = new Set(o.holidays || []);
  const d = dObj(o.today);
  $('#dow').textContent = (d.getMonth()+1)+'월 '+d.getDate()+'일 '+WD[(d.getDay()+6)%7]+'요일';
  $('#fulldate').textContent = o.is_business_day ? '영업일' : '영업일 아님';
  $('#tb-sub').textContent = o.stats.left ? o.stats.left+'건 남음' : '';
  $('#left').textContent = o.stats.left;
  const pct = o.stats.total ? o.stats.done / o.stats.total : (o.stats.left ? 0 : 1);
  $('#ringfg').style.strokeDashoffset = 188.5 * (1 - pct);
  $('#ringfg').style.stroke = o.stats.left ? 'var(--mid)' : 'var(--mint)';

  /* 지금 + 오늘 통합: 시간순, 완료는 아래로 */
  const rank = i => (i.done ? 1 : 0);
  const all = o.overdue.concat(o.todays).sort((a,b) =>
    rank(a)-rank(b) || (a.date||'').localeCompare(b.date||'') ||
    (a.time||'99:99').localeCompare(b.time||'99:99'));
  fill($('#today'), all, '오늘 할 일이 없습니다 ✓', {showOverdue:true});
  const undone = all.filter(i => !i.done).length;
  $('#c-today').textContent = all.length;
  $('#c-today').classList.toggle('hot', undone > 0);
  $('#today-note').textContent = all.length ? (undone ? undone+'건 남음' : '전부 완료') : '';

  fill($('#upcoming'), o.upcoming, '앞으로 7일, 마감 없음', {showDate:true});
  fill($('#floating'), o.floating, '＋ 새 항목 → 기한 없는 메모');
  fill($('#routines'), o.routines, '＋ 새 항목 → 반복되는 일', null, routineEl);
  $('#c-up').textContent = o.upcoming.length;
  $('#c-up').classList.toggle('hot', o.upcoming.length > 0);
  $('#c-rt').textContent = o.routines.length;
  $('#c-float').textContent = o.floating.length;
  $('#s-lead').value = o.settings.notify_min != null ? o.settings.notify_min : 30;
  $('#s-brief').value = o.settings.brief_time || '08:30';
  $('#s-biz').checked = bizOn();
  $('#s-auto').checked = !!o.settings.autostart;
  if($('#m-manage').classList.contains('on')) drawManage();
  if(view === 'cal') drawCal();
}

/* 시계 */
function tickClock(){
  const n = new Date();
  $('#clock').textContent = String(n.getHours()).padStart(2,'0')+':'+String(n.getMinutes()).padStart(2,'0');
}
tickClock();
setInterval(tickClock, 10000);

/* 반복 업무 카드 접기 (기본 접힘) */
const rtCard = $('#card-rt');
if(localStorage.getItem('rt-open') === '1') rtCard.classList.add('open');
function toggleRt(){
  rtCard.classList.toggle('open');
  localStorage.setItem('rt-open', rtCard.classList.contains('open') ? '1' : '0');
  // 화살표 방향은 CSS 가 회전으로 처리한다 (여기서 글리프까지 바꾸면 두 번 뒤집힌다)
}
$('#rt-head').onclick = toggleRt;

const load = () => api('/api/overview').then(o => {
  render(o);
  if(!load._first){                 /* 주소에 #cal 이 있으면 달력으로 시작 */
    load._first = true;
    if(location.hash === '#cal') setView('cal');
  }
});

/* ══════════ 모달 ══════════ */
function openM(id){ $('#veil').classList.add('on'); $(id).classList.add('on'); }
function closeM(id){ $(id).classList.remove('on'); if(!$$('.modal.on').length) $('#veil').classList.remove('on'); }
function closeAll(){ $('#veil').classList.remove('on'); $$('.modal').forEach(m => m.classList.remove('on')); }
$('#veil').onclick = closeAll;
$$('[data-close]').forEach(b => b.onclick = e => closeM('#'+e.target.closest('.modal').id));
document.onkeydown = e => {
  if(e.key === 'Escape'){
    if(!$$('.modal.on').length && rtCard.classList.contains('open')) return toggleRt();
    closeAll();
  }
  /* 달력을 보고 있을 때만 좌우로 달 넘기기 (입력 중에는 방해하지 않는다) */
  if(view === 'cal' && !$$('.modal.on').length && /^Arrow(Left|Right)$/.test(e.key)){
    shiftMonth(e.key === 'ArrowLeft' ? -1 : 1);
    return;
  }
  if(e.key === 'Enter' && e.target.tagName !== 'BUTTON'){
    if($('#m-add').classList.contains('on')) $('#a-save').click();
    else if($('#m-edit').classList.contains('on')) $('#e-save').click();
  }
};

/* ══════════ 반복 규칙: 주기 × 기준 ══════════ */
const PERIODS = [['day','매 영업일'],['week','매주'],['month','매월'],['quarter','분기']];

/* 기준을 "읽는 그대로" 한 줄 선택지로 펼침 */
const BASES = [
  ['bd_n',    'N번째 영업일',      '분기 N번째 영업일'],
  ['bd_last', '마지막 영업일',     '분기 마지막 영업일'],
  ['bebd_k',  '말일 K영업일 전',   '분기말 K영업일 전'],
  ['wd_n',    'N번째 O요일',       '분기 N번째 O요일'],
  ['wd_last', '마지막 O요일',      '분기 마지막 O요일'],
  ['day_n',   'N일',               '분기 N일째'],
  ['day_last','말일',              '분기 마지막 날'],
  ['be_k',    '말일 K일 전',       '분기말 K일 전'],
];
const MONTHSETS = [
  ['all',  '매월',        null],
  ['q1',   '3·6·9·12월',  [3,6,9,12]],
  ['q2',   '1·4·7·10월',  [1,4,7,10]],
  ['half', '6·12월',      [6,12]],
];
const sel = (f, opts, cur) => '<select data-f="'+f+'">'+opts.map(([v,l]) =>
  '<option value="'+v+'"'+(String(cur)===String(v)?' selected':'')+'>'+l+'</option>').join('')+'</select>';
const numSel = (f, from, to, cur, suffix) => '<select data-f="'+f+'">'+
  [...Array(to-from+1)].map((_,x)=>{const v=from+x;
    return '<option value="'+v+'"'+(String(cur)===String(v)?' selected':'')+'>'+v+(suffix||'')+'</option>';}).join('')+'</select>';

function basisKey(r){
  const b = r.basis || 'day', last = +r.n === -1;
  if(b === 'business_day') return last ? 'bd_last' : 'bd_n';
  if(b === 'weekday')      return last ? 'wd_last' : 'wd_n';
  if(b === 'before_end')   return 'be_k';
  if(b === 'before_end_bd')return 'bebd_k';
  return last ? 'day_last' : 'day_n';
}
function monthsKey(r){
  const m = r.months;
  if(!m || m.length === 12) return 'all';
  const hit = MONTHSETS.find(([,,set]) => set && set.length===m.length && set.every(x=>m.includes(x)));
  return hit ? hit[0] : 'custom';
}

/* ══════════ 폼 (추가 / 수정 공용) ══════════ */
function Form(box){
  const F = f => box.querySelector('[data-f="'+f+'"]');
  const self = {kind:'routine', box:box};

  const timeBlock = (t, lead, muted) =>
    '<div class="row"><div><label>마감 시각 <i class="opt">(비워도 됨)</i></label>'+
      '<input type="time" step="300" data-f="time" title="직접 입력할 수 있습니다 (5분 단위)" value="'+(t||'')+'"></div>'+
    '<div><label>알림 (분 전)</label><input type="number" class="min5" data-f="lead" min="0" step="5" placeholder="기본값 사용" value="'+(lead!=null?lead:'')+'"></div></div>'+
    '<label class="chk"><input type="checkbox" data-f="muted"'+(muted?' checked':'')+'> 이 항목은 알림 띄우지 않기</label>';

  /* ---------- 마감 ---------- */
  function renderDeadline(i){
    box.innerHTML =
      '<label>마감 날짜</label><input type="date" data-f="date" value="'+(i.date||rollBiz(STATE.today,1))+'">'+
      '<div class="quick">'+[['오늘',0],['내일',1],['모레',2],['+7일',7],['+30일',30]]
          .map(([l,n])=>'<button type="button" data-add="'+n+'">'+l+'</button>').join('')+
        '<button type="button" data-wd="0">다음 월요일</button><button type="button" data-wd="4">다음 금요일</button></div>'+
      '<div data-f="warn"></div>'+ timeBlock(i.time, i.notify_min, i.muted);
    const chk = () => {
      const v = F('date').value, w = F('warn');
      if(!v || !bizOn() || isBiz(v)){ w.innerHTML = ''; return; }
      const alt = rollBiz(v, -1);
      w.innerHTML = '<div class="warn-line">이 날은 영업일이 아닙니다 ('+fmtDay(v)+')'+
        '<button type="button" data-f="fix">'+fmtDay(alt)+'로</button></div>';
      w.querySelector('[data-f="fix"]').onclick = () => { F('date').value = alt; chk(); };
    };
    box.querySelectorAll('[data-add]').forEach(b => b.onclick = () => { F('date').value = shift(+b.dataset.add); chk(); });
    box.querySelectorAll('[data-wd]').forEach(b => b.onclick = () => { F('date').value = nextWd(+b.dataset.wd); chk(); });
    F('date').onchange = chk;
    chk();
  }

  /* ---------- 반복 ---------- */
  function renderRoutine(i){
    const r = i.rule_n || {period:'month', basis:'business_day', n:1};
    box.innerHTML =
      '<span class="step">1 · 얼마나 자주</span>'+ sel('period', PERIODS, r.period)+
      '<div data-f="detail"></div>'+
      timeBlock(i.time, i.notify_min, i.muted)+
      '<p class="preview" data-f="prev"><b>다음 실행 날짜</b>—</p>';

    const drawDetail = keep => {
      const p = F('period').value, q = (p === 'quarter');
      const rr = keep ? r : {};
      let h = '';
      if(p === 'day'){
        h = '<label class="chk"><input type="checkbox" data-f="biz"'+
            (rr.business_only !== false ? ' checked' : '')+'> 주말·공휴일 제외</label>';
      } else if(p === 'week'){
        h = '<span class="step">2 · 어느 요일 · 주기</span>'+
            '<div class="row"><div class="g15"><div class="wd" data-f="wd">'+
            WD.map((w,x)=> (bizOn() && x>4 && !(rr.weekdays||[]).includes(x)) ? '' :
              '<span data-w="'+x+'"'+((rr.weekdays||[]).includes(x)?' class="on"':'')+'>'+w+'</span>').join('')+
            '</div></div><div>'+sel('iv', [[1,'매주'],[2,'격주'],[3,'3주마다'],[4,'4주마다']], rr.interval||1)+
            '</div></div>';
      } else {
        h = '<span class="step">2 · 어느 날'+(q ? '' : ' · 실행하는 달')+'</span>'+
            '<div class="row"><div class="g15">'+
              sel('basis', BASES.map(([v,ml,ql])=>[v, q?ql:ml]), basisKey(rr))+
            '</div><div data-f="arg"></div>'+
            (q ? '' : '<div class="g11">'+sel('mset', MONTHSETS.map(([v,l])=>[v,l]), monthsKey(rr))+'</div>')+
            '</div>';
      }
      F('detail').innerHTML = h;
      if(p === 'month' || p === 'quarter') drawArg(keep);
      bind();
    };

    const drawArg = keep => {
      const rr = keep ? r : {};
      const k = F('basis').value, q = F('period').value === 'quarter';
      let h = '';
      if(k === 'bd_n')   h = numSel('n', 1, 20, keep&&rr.n>0?rr.n:1, '번째');
      if(k === 'day_n')  h = q ? numSel('n', 1, 92, keep&&rr.n>0?rr.n:1, '일째')
                              : numSel('n', 1, 31, keep&&rr.n>0?rr.n:1, '일');
      if(k === 'be_k' || k === 'bebd_k')
        h = '<div class="unit"><input type="number" data-f="k" min="0" max="'+(q?60:27)+'" value="'+
            (keep&&rr.k!=null?rr.k:3)+'"><span>'+(k==='be_k'?'일':'영업일')+' 전</span></div>';
      if(k === 'wd_n' || k === 'wd_last'){
        h = '<div class="row2">' + (k==='wd_n'
              ? sel('n', [[1,'첫째'],[2,'둘째'],[3,'셋째'],[4,'넷째']], keep&&rr.n>0?rr.n:1) : '')+
            sel('wdsel', WD.map((w,x)=>[x, w+'요일']).filter(([x])=>!(bizOn()&&x>4&&x!=rr.weekday)),
                keep&&rr.weekday!=null?rr.weekday:0)+'</div>';
      }
      F('arg').innerHTML = h;
    };

    const bind = () => {
      box.querySelectorAll('.wd span').forEach(s => s.onclick = () => { s.classList.toggle('on'); preview(); });
      if(F('basis')) F('basis').onchange = () => { drawArg(false); bind(); preview(); };
      box.querySelectorAll('[data-f="detail"] input, [data-f="detail"] select')
         .forEach(el => { if(el.dataset.f !== 'basis') el.onchange = preview; });
      preview();
    };

    const preview = () => {
      const rule = self.readRule();
      if(rule.period === 'week' && !rule.weekdays.length){
        F('prev').innerHTML = '<b>다음 실행 날짜</b>요일을 하나 이상 선택하세요'; return;
      }
      api('/api/preview', {rule})
        .then(d => F('prev').innerHTML = '<b>'+esc(d.text)+'</b>'+d.dates.join('   ·   '))
        .catch(() => {});
    };

    F('period').onchange = () => drawDetail(false);
    drawDetail(true);
  }

  self.render = function(kind, i){
    self.kind = kind;
    i = i || {};
    if(kind === 'floating'){
      box.innerHTML = '<p class="hint">기한 없이 목록에만 남습니다. 나중에 이 창에서 종류를 바꿔 마감을 붙일 수 있습니다.</p>';
    } else if(kind === 'deadline'){
      renderDeadline(i);
    } else {
      renderRoutine(i);
    }
  };

  self.readRule = function(){
    const p = F('period').value, r = {period:p, holiday_shift:'prev'};
    if(p === 'day'){ r.business_only = F('biz').checked; return r; }
    if(p === 'week'){
      r.weekdays = [...box.querySelectorAll('.wd span.on')].map(s=>+s.dataset.w);
      r.interval = +F('iv').value;
      return r;
    }
    const k = F('basis').value;
    r.basis = {bd_n:'business_day', bd_last:'business_day', wd_n:'weekday', wd_last:'weekday',
               be_k:'before_end', bebd_k:'before_end_bd', day_n:'day', day_last:'day'}[k];
    if(k === 'bd_last' || k === 'wd_last' || k === 'day_last') r.n = -1;
    else if(F('n')) r.n = +F('n').value;
    if(k === 'wd_n' || k === 'wd_last') r.weekday = +F('wdsel').value;
    if(k === 'be_k' || k === 'bebd_k') r.k = +F('k').value;
    if(p === 'month'){
      const ms = (MONTHSETS.find(m => m[0] === F('mset').value) || [])[2];
      if(ms) r.months = ms;
    }
    return r;
  };

  self.read = function(){
    const p = {kind:self.kind};
    if(self.kind === 'floating')
      return Object.assign(p, {due_date:null, due_time:'', rule:null, notify_min:null, muted:false});
    p.due_time = F('time').value || '';
    p.notify_min = F('lead').value === '' ? null : +F('lead').value;
    p.muted = F('muted').checked;
    if(self.kind === 'deadline'){ p.due_date = F('date').value || STATE.today; p.rule = null; }
    else { p.rule = self.readRule(); p.due_date = null; }
    return p;
  };

  self.valid = function(){
    if(self.kind === 'routine'){
      const r = self.readRule();
      if(r.period === 'week' && !r.weekdays.length){ say('요일을 하나 이상 선택하세요'); return false; }
    }
    return true;
  };
  return self;
}

/* ══════════ 새 항목 ══════════ */
const addForm = Form($('#a-body'));
let addKind = 'routine';
$('#add-tabs').onclick = e => {
  const b = e.target.closest('button'); if(!b) return;
  $$('#add-tabs button').forEach(x => x.classList.toggle('on', x === b));
  addKind = b.dataset.k;
  addForm.render(addKind, {});
};
function openAdd(kind, seed){
  $('#a-title').value = ''; $('#a-note').value = '';
  addKind = kind || 'routine';
  $$('#add-tabs button').forEach(x => x.classList.toggle('on', x.dataset.k === addKind));
  addForm.render(addKind, seed || {});
  openM('#m-add');
  setTimeout(() => $('#a-title').focus(), 90);
}
$('#btn-add').onclick = () => openAdd('routine', {});
$('#a-save').onclick = () => {
  const title = $('#a-title').value.trim();
  if(!title){ say('이름을 입력하세요'); return $('#a-title').focus(); }
  if(!addForm.valid()) return;
  api('/api/task', Object.assign({title, note:$('#a-note').value.trim()}, addForm.read()))
    .then(() => { closeM('#m-add'); say('추가됨 · '+title); load(); });
};

/* ══════════ 수정 ══════════ */
const editForm = Form($('#e-body'));
let EDIT = null;
function openEdit(i){
  EDIT = i;
  $('#e-title').value = i.title;
  $('#e-note').value = i.note || '';
  editForm.render(i.kind, i);
  $('#e-skip').hidden = i.kind !== 'routine';
  $('#m-edit').querySelector('h3').innerHTML = '항목 수정 <i class="opt">'+
    ({deadline:'마감', routine:'반복', floating:'메모'}[i.kind] || '')+'</i>';
  openM('#m-edit');
}
$('#e-save').onclick = () => {
  const title = $('#e-title').value.trim();
  if(!title){ say('이름을 입력하세요'); return $('#e-title').focus(); }
  if(!editForm.valid()) return;
  api('/api/task/'+EDIT.id, Object.assign({title, note:$('#e-note').value.trim()}, editForm.read()))
    .then(() => { closeM('#m-edit'); say('저장됨'); load(); });
};
$('#e-skip').onclick = () => {
  const day = EDIT.next_date || EDIT.date || STATE.today;
  api('/api/task/'+EDIT.id+'/skip', {date:day})
    .then(() => { closeM('#m-edit'); say(fmtDay(day)+' 회차 건너뜀'); load(); });
};
$('#e-del').onclick = () => confirmBox('삭제할까요?',
  '「'+EDIT.title+'」'+(EDIT.kind==='routine' ? ' 반복 일정 전체가 사라집니다. 이번 회차만 빼려면 건너뛰기를 쓰세요.' : ' 항목을 삭제합니다.'),
  () => api('/api/task/'+EDIT.id+'/delete', {}).then(() => { closeAll(); say('삭제됨'); load(); }));

function confirmBox(title, msg, onOk){
  $('#cf-title').textContent = title;
  $('#cf-msg').textContent = msg;
  $('#cf-ok').onclick = onOk;
  openM('#m-confirm');
}

/* ══════════ 달력 ══════════
   영업일만 쓰는 도구이므로 월~금 5칸만 만든다. 칸이 40% 넓어져서
   한 칸에 일정 여러 개를 넣어도 제목이 읽힌다.
   표시 대상은 "마감이 있는 일" 뿐이다. 반복 업무는 넣지 않는다 -
   매달 되풀이되는 항목이 칸을 다 차지해서 정작 마감이 안 보이게 된다. */
const CAL_MAX = 3;                  /* 한 칸에 보여줄 최대 개수, 나머지는 +N */
let calCur = null;                  /* 보고 있는 달 {y, m} - m 은 0~11 */
let view = 'home';

function deadlines(){
  return (STATE.tasks || []).filter(t => (t.kind || 'deadline') === 'deadline' && t.due_date);
}

/* 달력의 항목을 수정 창에 넘길 형태로 맞춘다 (STATE.tasks 는 저장 형식) */
function asItem(t){
  return {id:t.id, title:t.title, note:t.note || '', kind:'deadline', rule:null,
          date:t.due_date || null, time:t.due_time || '',
          notify_min:t.notify_min != null ? t.notify_min : null,
          muted:!!t.muted, rule_text:'', done:!!t.done};
}

/* 주말에 걸린 마감을 어느 칸에 놓을지.

   주말 칸이 없으므로 그냥 두면 화면에서 사라진다. 가까운 영업일 칸에 얹고
   칩에 실제 날짜를 적어 준다. 앞 영업일이 다른 달로 넘어가는 경우(1일이 일요일 등)
   에는 뒤로 미뤄서, 반드시 자기 달 안에서 보이게 한다. */
function isWeekend(d){ const w = dObj(d).getDay(); return w === 0 || w === 6; }

function cellDate(d){
  if(!isWeekend(d)) return d;
  const m = d.slice(0, 7);
  const back = dObj(d), fwd = dObj(d);
  while(isWeekend(iso(back))) back.setDate(back.getDate() - 1);
  if(iso(back).slice(0, 7) === m) return iso(back);
  while(isWeekend(iso(fwd))) fwd.setDate(fwd.getDate() + 1);
  return iso(fwd);
}

function chipEl(t){
  const el = document.createElement('div');
  const cls = t.done ? 'done' : t.due_date < STATE.today ? 'p'
            : t.due_date === STATE.today ? 't' : 'f';
  const wk = isWeekend(t.due_date);
  el.className = 'chip ' + cls + (wk ? ' wk' : '');
  const d = dObj(t.due_date);
  const head = wk ? d.getDate() + '일(' + WD[(d.getDay() + 6) % 7] + ')' : t.due_time;
  el.innerHTML = (head ? '<span class="h">' + head + '</span>' : '') +
                 '<span class="n2">' + esc(t.title) + '</span>';
  el.title = fmtDay(t.due_date) + (t.due_time ? ' ' + t.due_time : '') + '  ' + t.title +
             (wk ? String.fromCharCode(10) + '주말 마감이라 앞 영업일 칸에 표시했습니다' : '') +
             (t.note ? String.fromCharCode(10) + t.note : '') +
             (t.done ? String.fromCharCode(10) + '(완료)' : '');
  el.onclick = e => { e.stopPropagation(); openEdit(asItem(t)); };
  return el;
}

function dayModal(key, list){
  /* 주말 마감을 앞 영업일 칸에 얹었으므로, 목록에서는 실제 날짜를 밝혀 준다 */
  const wknd = list.filter(t => isWeekend(t.due_date)).length;
  $('#day-title').innerHTML = fmtDay(key) + ' <i class="opt">' + list.length + '건' +
    (wknd ? ' · 주말 마감 ' + wknd + '건 포함' : '') + '</i>';
  const box = $('#day-list');
  box.innerHTML = '';
  list.forEach(t => {
    const el = document.createElement('div');
    el.className = 'mg-row' + (t.done ? ' off' : '');
    const d = dObj(t.due_date);
    const when = (isWeekend(t.due_date)
        ? d.getDate() + '일(' + WD[(d.getDay() + 6) % 7] + ') ' : '') +
      (t.due_time || (isWeekend(t.due_date) ? '' : '시각 없음'));
    el.innerHTML = '<span class="k">마감</span><span class="n">' + esc(t.title) +
                   '</span><span class="w">' + esc(when.trim()) + '</span>';
    el.onclick = () => { closeM('#m-day'); openEdit(asItem(t)); };
    box.appendChild(el);
  });
  $('#day-add').onclick = () => { closeM('#m-day'); openAdd('deadline', {date:key}); };
  openM('#m-day');
}

function drawCal(){
  if(!STATE) return;
  if(!calCur){ const d = dObj(STATE.today); calCur = {y:d.getFullYear(), m:d.getMonth()}; }
  const y = calCur.y, m = calCur.m;
  $('#cal-ym').textContent = y + '년 ' + (m + 1) + '월';

  const byDate = {};
  deadlines().forEach(t => {
    const k = cellDate(t.due_date);
    (byDate[k] = byDate[k] || []).push(t);
  });
  Object.keys(byDate).forEach(k => byDate[k].sort((a, b) =>
    (a.done ? 1 : 0) - (b.done ? 1 : 0) ||
    a.due_date.localeCompare(b.due_date) ||
    (a.due_time || '99:99').localeCompare(b.due_time || '99:99')));

  const pre = y + '-' + String(m + 1).padStart(2, '0');
  const mine = deadlines().filter(t => t.due_date.slice(0, 7) === pre);
  const cnt = mine.length, left = mine.filter(t => !t.done).length;
  $('#cal-note').textContent = cnt ? cnt + '건 · ' + left + '건 남음' : '마감 없음';

  /* 그 달의 첫 주 월요일부터, 마지막 날이 포함된 주까지 */
  const first = new Date(y, m, 1), last = new Date(y, m + 1, 0);
  const cur = new Date(first);
  cur.setDate(first.getDate() - ((first.getDay() + 6) % 7));
  const hasWeekday = mon => {                 /* 그 주 월~금 중 이 달에 속한 날이 있나 */
    for(let k = 0; k < 5; k++){
      const d = new Date(mon); d.setDate(mon.getDate() + k);
      if(d.getMonth() === m) return true;
    }
    return false;
  };
  while(!hasWeekday(cur)) cur.setDate(cur.getDate() + 7);
  const grid = $('#cal-grid');
  grid.innerHTML = '';
  const HN = STATE.holiday_names || {};

  while(cur <= last && hasWeekday(cur)){
    for(let k = 0; k < 5; k++){                                   /* 월~금만 */
      const d = new Date(cur); d.setDate(cur.getDate() + k);
      const key = iso(d);
      const out = d.getMonth() !== m;
      const hol = HOL.has(key);
      const cell = document.createElement('div');
      cell.className = 'day' + (out ? ' out' : '') + (hol && !out ? ' hol' : '') +
                       (key === STATE.today ? ' now' : '');
      const num = key === STATE.today ? '<b>' + d.getDate() + '</b>' : d.getDate();
      cell.innerHTML = '<div class="n">' + num +
        (hol && !out ? '<span class="hn">' + esc(HN[key] || '공휴일') + '</span>' : '') +
        '</div>';
      if(!out){
        const list = byDate[key] || [];
        const chips = document.createElement('div');
        chips.className = 'chips';
        list.slice(0, CAL_MAX).forEach(t => chips.appendChild(chipEl(t)));
        cell.appendChild(chips);
        if(list.length > CAL_MAX){
          const more = document.createElement('div');
          more.className = 'more';
          more.textContent = '+' + (list.length - CAL_MAX) + '건 더';
          more.onclick = e => { e.stopPropagation(); dayModal(key, list); };
          cell.appendChild(more);
        }
        cell.onclick = () => list.length > CAL_MAX ? dayModal(key, list)
                                                   : openAdd('deadline', {date:key});
        cell.title = hol ? (HN[key] || '공휴일') + ' · 영업일이 아닙니다'
                         : '눌러서 이 날짜에 마감 추가';
      }
      grid.appendChild(cell);
    }
    cur.setDate(cur.getDate() + 7);
  }
}

function shiftMonth(n){
  if(!calCur){ const d = dObj(STATE.today); calCur = {y:d.getFullYear(), m:d.getMonth()}; }
  const t = new Date(calCur.y, calCur.m + n, 1);
  calCur = {y:t.getFullYear(), m:t.getMonth()};
  drawCal();
}

function setView(v){
  view = v;
  $$('#views button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
  $('#v-home').hidden = v !== 'home';
  $('#v-cal').hidden = v !== 'cal';
  if(v === 'cal') drawCal();
}
$('#views').onclick = e => {
  const b = e.target.closest('button');
  if(b) setView(b.dataset.v);
};
$('#cal-prev').onclick = () => shiftMonth(-1);
$('#cal-next').onclick = () => shiftMonth(1);
$('#cal-now').onclick = () => { calCur = null; drawCal(); };

/* ══════════ 전체 관리 ══════════ */
let mgKind = 'all';
$('#mg-tabs').onclick = e => {
  const b = e.target.closest('button'); if(!b) return;
  $$('#mg-tabs button').forEach(x => x.classList.toggle('on', x === b));
  mgKind = b.dataset.k; drawManage();
};
$('#btn-manage').onclick = () => { openM('#m-manage'); drawManage(); };

function drawManage(){
  const KN = {deadline:'마감', routine:'반복', floating:'메모'};
  let rows = STATE.tasks.slice();
  if(mgKind === 'done') rows = rows.filter(t => t.done);
  else if(mgKind !== 'all') rows = rows.filter(t => (t.kind||'deadline') === mgKind && !t.done);
  else rows = rows.filter(t => !t.done);

  const box = $('#mg-list');
  box.innerHTML = '';
  if(!rows.length){ box.innerHTML = '<div class="empty">해당 항목이 없습니다</div>'; return; }
  const byId = {};
  STATE.routines.forEach(r => byId[r.id] = r);
  rows.forEach(t => {
    const kind = t.kind || 'deadline';
    const rt = byId[t.id];
    const when = kind === 'routine' ? '↻ ' + (rt ? rt.rule_text : '반복')
               : kind === 'floating' ? '기한 없음'
               : (t.due_date ? fmtDay(t.due_date) : '날짜 없음') + (t.due_time ? ' ' + t.due_time : '');
    const el = document.createElement('div');
    el.className = 'mg-row' + (t.done ? ' off' : '');
    el.innerHTML = '<span class="k">'+KN[kind]+'</span><span class="n">'+esc(t.title)+
                   '</span><span class="w">'+esc(when)+'</span>';
    el.onclick = () => openEdit(rt || {
      id:t.id, title:t.title, note:t.note||'', kind:kind, rule:t.rule||null,
      date:t.due_date||null, time:t.due_time||'',
      notify_min:t.notify_min!=null?t.notify_min:null, muted:!!t.muted, rule_text:'', done:!!t.done
    });
    box.appendChild(el);
  });
}

/* ══════════ 설정 ══════════ */
$('#btn-settings').onclick = () => openM('#m-settings');
$('#s-save').onclick = () => api('/api/settings', {
    notify_min:+$('#s-lead').value, brief_time:$('#s-brief').value,
    business_only:$('#s-biz').checked, autostart:$('#s-auto').checked
  }).then(() => { closeM('#m-settings'); say('설정 저장됨'); load(); });
$('#s-shortcut').onclick = () => api('/api/shortcut', {})
  .then(r => say(r.ok ? '바탕화면에 바로가기를 만들었습니다' : '바로가기를 만들지 못했습니다'));
$('#s-test').onclick = () => api('/api/test-toast', {}).then(() => say('알림을 띄웠습니다 (우측 하단)'));
$('#s-quit').onclick = () => confirmBox('완전히 종료할까요?',
  '알림도 함께 멈춥니다. 바탕화면 아이콘으로 다시 시작할 수 있습니다.',
  () => { api('/api/quit', {}); setTimeout(() => window.pywebview ? window.pywebview.api.close() : window.close(), 400); });

load();
setInterval(load, 45000);
