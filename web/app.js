/* ระบบจัดทำงานวิจัยและโครงงาน — ส่วนหน้าเว็บ (SPA ไม่ใช้เฟรมเวิร์ก) */
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const app = $('#app');
const S = { user: null, meta: null, pid: null, proj: null, status: null, logs: [], lastLog: 0, tab: 'docs',
  docKey: 'ch1', doc: null, changed: [], chat: [], timer: null };

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const rich = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*(.+?)\*/g, '<i>$1</i>')
  .replace(/⟦(.+?)⟧/g, '<mark>[$1]</mark>').replace(/\n/g, '<br>');

function toast(msg, isErr) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'show' + (isErr ? ' err' : '');
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.className = ''), isErr ? 6000 : 3000);
}

async function api(path, { method = 'GET', body, form } = {}) {
  const opt = { method, headers: { 'X-Requested-With': 'research-app' }, credentials: 'same-origin' };
  if (form) opt.body = form;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch('/api' + path, opt);
  let d = {};
  try { d = await r.json(); } catch { /* ไม่ใช่ JSON */ }
  if (!r.ok) {
    if (r.status === 401 && S.user) { S.user = null; route(); }
    throw new Error(d.error || `เกิดข้อผิดพลาด (${r.status})`);
  }
  return d;
}

/** ผูกปุ่มกับงาน async: ปิดปุ่มระหว่างทำ และแจ้งข้อผิดพลาด */
async function busy(btn, fn) {
  const old = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = 'กำลังดำเนินการ…'; }
  try { return await fn(); } catch (e) { toast(e.message, true); } finally {
    if (btn && btn.isConnected) { btn.disabled = false; btn.innerHTML = old; }
  }
}

// ------------------------------------------------------------------ router
window.addEventListener('hashchange', route);
async function route() {
  clearInterval(S.timer);
  if (!S.meta) S.meta = await api('/meta');
  if (!S.user) {
    S.user = (await api('/me')).user;
    if (!S.user) return viewAuth();
  }
  const h = location.hash.replace(/^#\/?/, '');
  const m = h.match(/^p\/(\d+)(?:\/(\w+))?/);
  if (m) return viewProject(+m[1], m[2]);
  if (h === 'new') return viewNew();
  if (h === 'admin' && S.user.role === 'admin') return viewAdmin();
  if (h === 'account') return viewAccount();
  return viewProjects();
}

function shell(inner, active = '') {
  const u = S.user;
  app.innerHTML = `<header class="topbar">
    <a class="brand" href="#/">ระบบจัดทำงานวิจัยและโครงงาน</a>
    <nav><a href="#/" class="${active === 'home' ? 'on' : ''}">งานของฉัน</a>
      <a href="#/new" class="${active === 'new' ? 'on' : ''}">+ ${u.role === 'student' ? 'สร้างโครงงานใหม่' : u.role === 'teacher' ? 'สร้างงานวิจัยใหม่' : 'สร้างงานใหม่'}</a>
      ${u.role === 'admin' ? `<a href="#/admin" class="${active === 'admin' ? 'on' : ''}">ผู้ดูแลระบบ</a>` : ''}</nav>
    <div class="who"><a href="#/account" style="color:#fff">${esc(u.full_name)}</a>
      <span class="badge">${esc(S.meta.roles[u.role])}</span><button id="logout" class="sm">ออกจากระบบ</button></div>
  </header><main>${inner}</main>`;
  $('#logout').onclick = async () => { await api('/auth/logout', { method: 'POST' }); S.user = null; location.hash = '#/'; route(); };
}

// ------------------------------------------------------------------ เข้าสู่ระบบ / สมัคร
function viewAuth(mode = 'login', note = '') {
  const reg = mode === 'register';
  app.innerHTML = `<div class="auth"><h1>ระบบจัดทำงานวิจัยและโครงงาน</h1>
    <p class="sub">สำหรับนักเรียน นักศึกษา และครู</p>
    <div class="card"><div class="tabs"><button data-m="login" class="${reg ? '' : 'on'}">เข้าสู่ระบบ</button>
      ${S.meta.allow_register ? `<button data-m="register" class="${reg ? 'on' : ''}">สมัครใช้งาน</button>` : ''}</div>
    ${note ? `<div class="msg ok">${esc(note)}</div>` : ''}
    <form id="f">
      ${reg ? `<label for="role">ประเภทผู้ใช้</label><select id="role"><option value="student">นักเรียน/นักศึกษา</option><option value="teacher">ครู (รอผู้ดูแลระบบอนุมัติ)</option></select>
        <label for="full_name">ชื่อ-สกุล</label><input id="full_name" required autocomplete="name">
        <div id="classfields" class="grid2"><div><label for="level">ระดับ</label><select id="level" required><option value="">— เลือก —</option>${S.meta.levels.map(l => `<option>${esc(l)}</option>`).join('')}</select></div>
          <div><label for="group_name">กลุ่ม</label><input id="group_name" required placeholder="เช่น 2/1 เทคโนโลยีธุรกิจดิจิทัล"></div></div>
        <label for="org">สถานศึกษา</label><input id="org" value="${esc(S.meta.default_org)}" required autocomplete="organization">` : ''}
      <label for="username">${reg ? 'อีเมล <span class="muted">(ใช้เป็นชื่อผู้ใช้)</span>' : 'อีเมล (ชื่อผู้ใช้)'}</label>
      <input id="username" ${reg ? 'type="email" placeholder="name@example.com"' : ''} required autocomplete="username">
      <label for="password">รหัสผ่าน ${reg ? '<span class="muted">(อย่างน้อย 8 ตัวอักษร)</span>' : ''}</label>
      <input id="password" type="password" required autocomplete="${reg ? 'new-password' : 'current-password'}">
      <div id="err"></div>
      <button class="primary" style="width:100%;justify-content:center;margin-top:16px">${reg ? 'สมัครใช้งาน' : 'เข้าสู่ระบบ'}</button>
    </form></div></div>`;
  $$('.tabs button').forEach(b => (b.onclick = () => viewAuth(b.dataset.m)));
  if (reg) {  // ระดับและกลุ่มถามเฉพาะนักเรียน/นักศึกษา
    const sync = () => { const student = $('#role').value === 'student';
      $('#classfields').classList.toggle('hidden', !student);
      $$('#classfields select, #classfields input').forEach(i => { i.required = student; i.disabled = !student; }); };
    $('#role').onchange = sync; sync();
  }
  $('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries($$('#f input, #f select').map(i => [i.id, i.value]));
    try {
      const r = await api(reg ? '/auth/register' : '/auth/login', { method: 'POST', body: d });
      if (r.pending) return viewAuth('login', 'สมัครสำเร็จ กรุณารอผู้ดูแลระบบอนุมัติบัญชีครูก่อนเข้าสู่ระบบ');
      route();
    } catch (err) { $('#err').innerHTML = `<div class="msg err">${esc(err.message)}</div>`; }
  };
}

function viewAccount() {
  const u = S.user, student = u.role === 'student';
  shell(`<div class="card" style="max-width:560px"><h2>บัญชีของฉัน</h2>
    <p class="muted">${esc(u.username)} · ${esc(S.meta.roles[u.role])}</p>
    ${student && !(u.level && u.group_name) ? '<div class="msg warn">กรุณาเลือกระดับและกรอกกลุ่มให้ครบ</div>' : ''}
    <form id="fp"><label for="full_name">ชื่อ-สกุล</label><input id="full_name" value="${esc(u.full_name)}" required autocomplete="name">
    ${student ? `<div class="grid2"><div><label for="level">ระดับ</label><select id="level" required><option value="">— เลือก —</option>${S.meta.levels.map(l => `<option ${l === u.level ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
      <div><label for="group_name">กลุ่ม</label><input id="group_name" value="${esc(u.group_name || '')}" required placeholder="เช่น 2/1 เทคโนโลยีธุรกิจดิจิทัล"></div></div>` : ''}
    <label for="org">สถานศึกษา</label><input id="org" value="${esc(u.org || S.meta.default_org)}" autocomplete="organization">
    <button class="primary" style="margin-top:14px">บันทึกข้อมูล</button></form>
    <hr style="border:0;border-top:1px solid var(--line);margin:22px 0"><h3>เปลี่ยนรหัสผ่าน</h3>
    <form id="f"><label for="old">รหัสผ่านเดิม</label><input id="old" type="password" required autocomplete="current-password">
    <label for="new">รหัสผ่านใหม่ <span class="muted">(อย่างน้อย 8 ตัวอักษร)</span></label><input id="new" type="password" required autocomplete="new-password">
    <button style="margin-top:14px">เปลี่ยนรหัสผ่าน</button></form></div>`);
  $('#fp').onsubmit = e => { e.preventDefault(); busy(e.submitter, async () => {
    await api('/me/profile', { method: 'POST', body: Object.fromEntries($$('#fp input, #fp select').map(i => [i.id, i.value])) });
    S.user = (await api('/me')).user; toast('บันทึกข้อมูลแล้ว'); viewAccount();
  }); };
  $('#f').onsubmit = e => { e.preventDefault(); busy(e.submitter, async () => {
    await api('/me/password', { method: 'POST', body: { old: $('#old').value, new: $('#new').value } });
    toast('เปลี่ยนรหัสผ่านแล้ว'); e.target.reset();
  }); };
}

// ------------------------------------------------------------------ รายการงาน
async function viewProjects() {
  shell('<p class="boot">กำลังโหลด…</p>', 'home');
  const { projects } = await api('/projects');
  const role = S.user.role;
  const card = p => `<div class="card pcard"><a class="plink" href="#/p/${p.id}">
    <div class="row"><span class="badge">${esc(p.kind_label)}</span>
      ${p.running ? '<span class="badge warn">กำลังทำงาน</span>' : p.error ? '<span class="badge err">มีขั้นตอนผิดพลาด</span>' : p.done === p.total ? '<span class="badge ok">เสร็จสมบูรณ์</span>' : ''}
      ${!p.mine && p.advisor_id === S.user.id ? '<span class="badge gray">ฉันเป็นที่ปรึกษา</span>' : ''}</div>
    <h3>${esc(p.title)}</h3>
    <div class="bar"><i style="width:${Math.round(100 * p.done / p.total)}%"></i></div>
    <div class="small muted">เสร็จ ${p.done}/${p.total} ขั้นตอน · ${esc(p.mine ? '' : p.owner_name + ' · ')}แก้ไขล่าสุด ${esc(p.updated_at.slice(0, 16))}</div></a>
    <div class="row" style="margin-top:12px"><a class="btn sm" href="#/p/${p.id}">เปิดงาน</a>
      ${p.mine ? `<a class="btn sm" href="#/p/${p.id}/info">✎ แก้ไขข้อมูลงาน</a>` : '<span class="small muted">ดูได้อย่างเดียว</span>'}
      ${p.can_delete ? `<button class="sm danger right" data-del="${p.id}" data-title="${esc(p.title)}" data-owner="${esc(p.mine ? '' : p.owner_name)}">ลบงาน</button>` : ''}</div></div>`;
  shell(`<div class="page-head"><div><h1>${role === 'admin' ? 'งานทั้งหมดในระบบ' : 'งานของฉัน'}</h1>
      <p class="muted" style="margin:4px 0 0">${role === 'teacher' ? 'งานวิจัยในชั้นเรียนของท่าน และโครงงานของนักเรียนที่เลือกท่านเป็นครูที่ปรึกษา' : role === 'student' ? 'โครงงานที่ท่านจัดทำ' : 'ผู้ดูแลระบบเห็นงานของผู้ใช้ทุกคน'}</p></div>
      <a class="btn primary right" href="#/new">+ สร้างงานใหม่</a></div>
    ${projects.length ? `<div class="plist">${projects.map(card).join('')}</div>`
      : '<div class="card empty"><p>ยังไม่มีงาน</p><a class="btn primary" href="#/new">เริ่มสร้างงานแรก</a></div>'}`, 'home');
  // ลบงาน: เจ้าของลบงานของตน ผู้ดูแลระบบลบงานของผู้ใช้คนใดก็ได้ (ยืนยันก่อนทุกครั้ง ลบแล้วกู้คืนไม่ได้)
  $$('[data-del]').forEach(b => (b.onclick = () => {
    const whose = b.dataset.owner ? ` ของ ${b.dataset.owner}` : '';
    if (!confirm(`ลบงาน${whose}\n“${b.dataset.title}”\nพร้อมไฟล์ทั้งหมดอย่างถาวร?`)) return;
    busy(b, async () => { await api(`/projects/${b.dataset.del}`, { method: 'DELETE' }); toast('ลบงานแล้ว'); viewProjects(); });
  }));
}

// ------------------------------------------------------------------ สร้างงานใหม่ (เก็บ requirement)
// ข้อความของฟอร์มแยกตามประเภทงาน: โครงงานของนักเรียน/นักศึกษา กับงานวิจัยของครู ถามคนละแบบ
const KIND_FORM = {
  student_project: {
    intro: n => `พิมพ์ requirement ของโครงงาน แล้วระบบจะดำเนินการให้ครบ 7 ขั้นตอน: ค้นและดาวน์โหลดงานวิจัยจริงอย่างน้อย ${n} เรื่อง → เขียนบทที่ 1–4 → บรรณานุกรม APA → แบบเสนอโครงงาน พร้อมไฟล์ Word และ PDF ในแต่ละโฟลเดอร์`,
    req: 'พิมพ์สิ่งที่จะพัฒนาให้ละเอียดที่สุด เช่น พัฒนาเว็บแอปพลิเคชันจองห้องประชุมของวิทยาลัย ให้ครูและนักศึกษาจองผ่านมือถือได้ มีระบบแจ้งเตือน ต้องการประเมินคุณภาพโดยผู้เชี่ยวชาญและความพึงพอใจของผู้ใช้',
    fields: [['title', 'ชื่อโครงงาน', 'ถ้ายังไม่มี ระบบจะตั้งชื่อให้จาก requirement'], ['level', 'ระดับชั้น/สาขาวิชาของผู้จัดทำ', 'เช่น ปวส.2 เทคโนโลยีธุรกิจดิจิทัล'],
      ['subject', 'รายวิชา', 'เช่น โครงงาน'], ['institution', 'สถานศึกษา', ''], ['problem', 'ปัญหาหรือความต้องการของผู้ใช้', 'เช่น การจองห้องด้วยสมุดทำให้จองซ้ำและตรวจสอบยาก'],
      ['innovation', 'ชิ้นงานที่จะพัฒนา/เครื่องมือที่ใช้', 'เช่น เว็บแอปพลิเคชัน ด้วย Canva, Google Sites, AppSheet']],
    extra: 'เช่น กลุ่มตัวอย่างนักศึกษา ปวส.1 จำนวน 30 คน, ประเมินความพึงพอใจ 5 ระดับ',
  },
  classroom_research: {
    intro: n => `พิมพ์ requirement ของงานวิจัยในชั้นเรียน แล้วระบบจะดำเนินการให้ครบ 7 ขั้นตอน: ค้นและดาวน์โหลดงานวิจัยจริงอย่างน้อย ${n} เรื่อง → เขียนบทที่ 1–4 → บรรณานุกรม APA → โครงร่างงานวิจัย 3 บท พร้อมไฟล์ Word และ PDF ในแต่ละโฟลเดอร์`,
    req: 'พิมพ์ปัญหาในชั้นเรียนและวิธีที่จะใช้แก้ให้ละเอียดที่สุด เช่น นักเรียน ปวช.1 อ่านแบบงานเครื่องกลไม่ได้ ต้องการใช้ชุดฝึกทักษะร่วมกับการสอนแบบสาธิต วัดผลสัมฤทธิ์ก่อน-หลังเรียนและความพึงพอใจ',
    fields: [['title', 'ชื่อเรื่อง', 'ถ้ายังไม่มี ระบบจะตั้งชื่อเรื่องให้จาก requirement'], ['level', 'ระดับชั้น/ห้องของผู้เรียนกลุ่มเป้าหมาย', 'เช่น ปวช.2/1 สาขาช่างยนต์, ม.4/2'],
      ['subject', 'รายวิชาและหน่วยการเรียนรู้', ''], ['institution', 'สถานศึกษา', ''], ['problem', 'สภาพปัญหาที่พบในชั้นเรียน', 'เช่น ผู้เรียนมีผลสัมฤทธิ์เรื่อง…ต่ำกว่าเกณฑ์'],
      ['innovation', 'วิธีสอน/นวัตกรรมที่จะใช้', 'เช่น ชุดฝึกทักษะ, การเรียนรู้แบบโครงงานเป็นฐาน, เกม']],
    extra: 'เช่น ใช้แบบแผนกลุ่มเดียววัดก่อน-หลัง, ต้องมีแบบสอบถามความพึงพอใจ 5 ระดับ',
  },
};
KIND_FORM.research = { ...KIND_FORM.classroom_research,
  req: 'พิมพ์สิ่งที่ต้องการวิจัยและพัฒนาให้ละเอียดที่สุด เช่น พัฒนาชุดกิจกรรมการเรียนรู้…เพื่อส่งเสริม…ของนักศึกษาระดับ… หาประสิทธิภาพ เปรียบเทียบก่อน-หลัง และศึกษาความพึงพอใจ' };
const REQ_KEYS = ['requirement', 'extra', 'department', 'period', 'members', 'title', 'level', 'subject', 'institution', 'problem', 'innovation'];

function reqForm(req = {}, kind = 'classroom_research') {
  const f = KIND_FORM[kind] || KIND_FORM.research, student = kind === 'student_project';
  return `<label for="requirement">Requirement — ${student ? 'อธิบายโครงงานที่ต้องการทำ' : 'อธิบายงานวิจัยที่ต้องการทำ'}</label>
    <textarea id="requirement" rows="6" required placeholder="${esc(f.req)}">${esc(req.requirement || '')}</textarea>
    <div class="grid2">${f.fields.map(([k, label, ph]) => `<div><label for="${k}">${label} <span class="muted">(ไม่บังคับ)</span></label>
      <input id="${k}" value="${esc(req[k] || '')}" placeholder="${esc(ph)}"></div>`).join('')}</div>
    <label for="extra">ข้อกำหนดเพิ่มเติม <span class="muted">(ไม่บังคับ)</span></label>
    <textarea id="extra" rows="2" placeholder="${esc(f.extra)}">${esc(req.extra || '')}</textarea>
    ${student ? `<h3 style="margin-top:20px;font-size:17px">ข้อมูลสำหรับแบบเสนอโครงงาน <span class="muted small">(ไม่บังคับ — ส่วนที่เว้นไว้จะเป็นช่องให้เติมในแบบฟอร์ม)</span></h3>
    <div class="grid2"><div><label for="department">แผนกวิชา</label><input id="department" value="${esc(req.department || '')}" placeholder="เช่น เทคโนโลยีธุรกิจดิจิทัล"></div>
      <div><label for="period">ระยะเวลาดำเนินการ</label><input id="period" value="${esc(req.period || '')}" placeholder="เช่น ตุลาคม 2569 ถึง กุมภาพันธ์ 2570"></div></div>
    <label for="members">ผู้รับผิดชอบโครงงาน <span class="muted">(บรรทัดละ 1 คน: ชื่อ-สกุล, เลขประจำตัว)</span></label>
    <textarea id="members" rows="2" placeholder="นายสมชาย ใจดี, 66201010001&#10;นางสาวสมหญิง รักเรียน, 66201010002">${esc(req.members || '')}</textarea>` : ''}`;
}
// ช่องที่ประเภทงานนั้นไม่มี (เช่น ข้อมูลแบบเสนอโครงงานของงานวิจัยครู) ส่งเป็นค่าว่าง
const readReq = () => Object.fromEntries(REQ_KEYS.map(k => [k, ($('#' + k) || {}).value || '']));

async function viewNew() {
  shell('<p class="boot">กำลังโหลด…</p>', 'new');
  const { teachers } = await api('/teachers');
  const kinds = S.meta.role_kinds[S.user.role];  // นักเรียน/นักศึกษา: โครงงาน, ครู: วิจัยในชั้นเรียน
  const render = (kind, keep = {}) => {
    const student = kind === 'student_project';
    shell(`<div class="page-head"><h1>${student ? 'สร้างโครงงานใหม่' : 'สร้างงานวิจัยใหม่'}</h1></div>
      <form id="f" class="card" style="max-width:900px">
      <div class="msg info">${KIND_FORM[kind].intro(S.meta.min_papers)}</div>
      <div class="grid2"><div><label for="kind">ประเภทงาน</label>${kinds.length > 1
        ? `<select id="kind">${kinds.map(k => `<option value="${k}" ${k === kind ? 'selected' : ''}>${esc(S.meta.kinds[k])}</option>`).join('')}</select>`
        : `<input id="kind" type="hidden" value="${kind}"><input value="${esc(S.meta.kinds[kind])}" disabled aria-label="ประเภทงาน">`}</div>
      ${student ? `<div><label for="advisor_id">ครูที่ปรึกษา <span class="muted">(ไม่บังคับ — ครูจะเห็นงานและให้ความเห็นได้)</span></label>
        <select id="advisor_id"><option value="">— ไม่ระบุ —</option>${teachers.filter(t => t.id !== S.user.id).map(t => `<option value="${t.id}">${esc(t.full_name)}${t.org ? ' · ' + esc(t.org) : ''}</option>`).join('')}</select></div>` : '<div></div>'}</div>
      ${reqForm(keep, kind)}
      <div class="row" style="margin-top:18px"><button class="primary">${student ? 'สร้างโครงงานและเริ่มดำเนินการ' : 'สร้างงานวิจัยและเริ่มดำเนินการ'}</button><a class="btn" href="#/">ยกเลิก</a></div></form>`, 'new');
    if (kinds.length > 1) $('#kind').onchange = e => render(e.target.value, readReq());  // ผู้ดูแลระบบเปลี่ยนประเภท: คงข้อความที่พิมพ์ไว้
    $('#f').onsubmit = e => { e.preventDefault(); busy(e.submitter, async () => {
      const r = await api('/projects', { method: 'POST', body: { ...readReq(), kind: $('#kind').value, advisor_id: ($('#advisor_id') || {}).value || null } });
      location.hash = `#/p/${r.id}`;
    }); };
  };
  const me = S.user;  // เติมข้อมูลจากตอนสมัครให้ก่อน แก้ไขได้
  render(kinds[0], { institution: me.org || '', level: me.role === 'student' ? [me.level, me.group_name && `กลุ่ม ${me.group_name}`].filter(Boolean).join(' ') : '' });
}

// ------------------------------------------------------------------ หน้าโครงการ
async function viewProject(pid, tab) {
  if (S.pid !== pid) Object.assign(S, { pid, logs: [], lastLog: 0, tab: 'docs', docKey: 'ch1', doc: null, chat: [], changed: [] });
  if (tab) {  // เข้ามาด้วยลิงก์ "แก้ไขข้อมูลงาน": เปิดแท็บนั้นแล้วคงที่อยู่เป็น #/p/<id>
    if (['docs', 'papers', 'info', 'comments'].includes(tab)) S.tab = tab;
    history.replaceState(null, '', `#/p/${pid}`);
  }
  shell('<p class="boot">กำลังโหลด…</p>');
  let d;
  try { d = await api(`/projects/${pid}`); } catch (e) { return shell(`<div class="card empty">${esc(e.message)}<br><a href="#/">กลับหน้ารายการ</a></div>`); }
  S.proj = d; S.status = d.status; S.logs = d.status.logs; S.lastLog = S.logs.length ? S.logs.at(-1).id : 0;
  const p = d.project;
  // งานของตนเองที่ยังไม่มีเอกสาร (เช่น ขั้นแรกผิดพลาด): พาไปหน้าข้อมูลงานเพื่อแก้ไขแล้วสั่งทำใหม่
  if (!tab && d.can_edit && !d.status.running && !d.status.docs.some(x => x.available)) S.tab = 'info';
  shell(`<div class="page-head"><div style="flex:1;min-width:260px"><a href="#/" class="small">← กลับหน้ารายการ</a>
      <h1 id="ptitle"></h1><div class="row small muted" style="margin-top:6px"><span class="badge">${esc(d.kind_label)}</span>
      <span>ผู้จัดทำ: ${esc(p.owner_name)}</span>${p.advisor_name ? `<span>ครูที่ปรึกษา: ${esc(p.advisor_name)}</span>` : ''}
      ${d.can_edit ? '' : '<span class="badge gray">ดูและให้ความเห็นได้อย่างเดียว — แก้ไขได้เฉพาะเจ้าของงาน</span>'}</div></div>
      ${d.can_edit ? '<button id="editp">✎ แก้ไขข้อมูลงาน</button>' : ''}
      <a class="btn" href="/api/projects/${pid}/download-all">⬇ ดาวน์โหลดทุกโฟลเดอร์ (.zip)</a>
      ${d.can_delete ? '<button id="delp" class="danger">ลบงาน</button>' : ''}</div>
    <div class="work"><aside class="card"><div class="row"><h2 style="font-size:18px">ขั้นตอน</h2><span id="runbtns" class="row right"></span></div>
        <ol class="steps" id="steps"></ol><div class="log" id="log" aria-label="บันทึกการทำงาน"></div>
        ${d.folder ? `<p class="small muted" style="overflow-wrap:anywhere">โฟลเดอร์บนเซิร์ฟเวอร์: ${esc(d.folder)}</p>` : ''}</aside>
      <section class="card"><div class="tabs" id="tabs"></div><div id="tab"></div></section></div>`);
  if (d.can_edit) $('#editp').onclick = () => { S.tab = 'info'; renderTabs(); $('#tabs').scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  if (d.can_delete) $('#delp').onclick = e => confirm('ลบงานนี้และไฟล์ทั้งหมดอย่างถาวร?') && busy(e.target, async () => {
    await api(`/projects/${pid}`, { method: 'DELETE' }); location.hash = '#/';
  });
  renderStatus(); renderTabs();
  S.timer = setInterval(poll, 2500);
}

async function poll() {
  if (!S.status || location.hash !== `#/p/${S.pid}`) return;
  const wasRunning = S.status.running;
  if (!wasRunning && document.hidden) return;
  let st;
  try { st = await api(`/projects/${S.pid}/status?after=${S.lastLog}`); } catch { return; }
  const before = JSON.stringify([S.status.steps, S.status.docs, S.status.n_papers, S.status.title_th]);
  S.logs.push(...st.logs); if (st.logs.length) S.lastLog = st.logs.at(-1).id;
  S.status = st;
  if (st.logs.length || before !== JSON.stringify([st.steps, st.docs, st.n_papers, st.title_th])) {
    renderStatus();
    // เนื้อหาเปลี่ยนเพราะระบบทำงานเสร็จบางขั้น: โหลดแท็บใหม่ (ยกเว้นกำลังพิมพ์แก้ไขอยู่)
    if (!$('#tab textarea:focus, #tab [contenteditable]:focus, #tab input:focus') && before !== JSON.stringify([st.steps, st.docs, st.n_papers, st.title_th])) {
      S.doc = null; renderTabs();
    }
  }
}

function renderStatus() {
  const st = S.status, can = S.proj.can_edit;
  $('#ptitle').textContent = st.title_th || S.proj.project.requirement.title || 'กำลังวิเคราะห์ requirement…';
  const icon = { done: '✓', error: '!', running: '…', queued: '·', pending: '' };
  $('#steps').innerHTML = st.steps.map((s, i) => `<li class="${s.status}"><span class="dot">${icon[s.status] || i}</span>
    <div><div class="lbl">${esc(s.label)}</div><div class="smsg">${esc(s.status === 'running' ? 'กำลังดำเนินการ…' : s.status === 'queued' ? 'รอคิว' : s.msg || '')}</div></div>
    ${can && !st.running ? `<button class="sm ghost" data-step="${s.key}" title="ทำขั้นตอนนี้ใหม่">↻</button>` : ''}</li>`).join('');
  const next = st.steps.find(s => s.status !== 'done');
  $('#runbtns').innerHTML = !can ? '' : st.running ? '<button id="cancel" class="sm danger">■ ยกเลิก</button>'
    : next ? `<button id="go" class="sm primary">▶ ${next.key === 'plan' ? 'เริ่มทุกขั้นตอน' : 'ทำต่อ'}</button>` : '<span class="badge ok">ครบทุกขั้นตอน</span>';
  const run = body => busy(null, async () => { await api(`/projects/${S.pid}/run`, { method: 'POST', body }); S.status.running = true; poll(); });
  if ($('#go')) $('#go').onclick = () => run({ from: next.key });
  if ($('#cancel')) $('#cancel').onclick = () => busy(null, () => api(`/projects/${S.pid}/cancel`, { method: 'POST' }).then(() => toast('จะหยุดเมื่อจบงานย่อยที่กำลังทำ')));
  $$('#steps [data-step]').forEach(b => (b.onclick = () => {
    const label = st.steps.find(s => s.key === b.dataset.step).label;
    if (confirm(`ทำขั้นตอน “${label}” ใหม่?\n(เนื้อหาเดิมของขั้นตอนนี้จะถูกแทนที่ — ย้อนกลับได้ด้วยปุ่ม ↶ ในหน้าเอกสาร)`)) run({ steps: [b.dataset.step] });
  }));
  const log = $('#log'), atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
  log.innerHTML = S.logs.map(l => `<div class="${l.level}"><span class="t">${esc(l.ts.slice(11, 19))}</span>${esc(l.msg)}</div>`).join('')
    || '<div class="t">ยังไม่มีบันทึกการทำงาน</div>';
  if (atEnd) log.scrollTop = log.scrollHeight;
}

function renderTabs() {
  const tabs = [['docs', 'เอกสาร'], ['papers', `งานวิจัยที่เกี่ยวข้อง (${S.status.n_papers})`], ['info', 'ข้อมูลงาน'], ['comments', 'ความคิดเห็น']];
  $('#tabs').innerHTML = tabs.map(([k, v]) => `<button data-t="${k}" class="${S.tab === k ? 'on' : ''}">${v}</button>`).join('');
  $$('#tabs button').forEach(b => (b.onclick = () => { S.tab = b.dataset.t; renderTabs(); }));
  ({ docs: tabDocs, papers: tabPapers, info: tabInfo, comments: tabComments })[S.tab]();
}

// ---- แท็บเอกสาร
async function tabDocs() {
  const el = $('#tab'), docs = S.status.docs, can = S.proj.can_edit;
  if (!docs.find(d => d.key === S.docKey && d.available)) S.docKey = (docs.find(d => d.available) || docs[1]).key;
  const cur = docs.find(d => d.key === S.docKey);
  const pills = `<div class="docpills">${docs.map(d => `<button data-k="${d.key}" class="${d.key === S.docKey ? 'on' : ''}" ${d.available ? '' : 'disabled title="ยังไม่ได้สร้าง"'}>${esc(d.title)}${d.stale && d.available ? ' <span title="รายการงานวิจัยเปลี่ยนหลังเขียนบทนี้">⚠</span>' : ''}</button>`).join('')}</div>`;
  if (!cur.available) {
    el.innerHTML = pills + `<div class="empty">${S.status.running ? 'ระบบกำลังดำเนินการ เอกสารจะปรากฏที่นี่เมื่อแต่ละขั้นตอนเสร็จ' : 'ยังไม่มีเอกสาร กด ▶ ที่แผงขั้นตอนเพื่อเริ่ม'}</div>`;
  } else {
    if (!S.doc || S.doc.key !== S.docKey) {
      el.innerHTML = pills + '<p class="boot">กำลังโหลดเอกสาร…</p>';
      try { S.doc = { key: S.docKey, ...(await api(`/projects/${S.pid}/doc/${S.docKey}`)) }; } catch (e) { el.innerHTML = pills + `<div class="msg err">${esc(e.message)}</div>`; return; }
      if (S.tab !== 'docs') return;
    }
    const editable = can && S.doc.editable && !S.status.running;
    const dl = ext => `/api/projects/${S.pid}/download/${S.docKey}.${ext}`;
    const staleMsg = cur.stale ? `<div class="msg warn">รายการงานวิจัยที่เกี่ยวข้องเปลี่ยนไปหลังจากเขียนบทนี้ การอ้างอิงในเนื้อหาอาจไม่ตรงกับรายการปัจจุบัน${can ? ' — กด ↻ ที่ขั้นตอนของบทนี้เพื่อเขียนใหม่ หรือแก้การอ้างอิงเอง' : ''}</div>` : '';
    el.innerHTML = pills + staleMsg + `<div class="row" style="margin-bottom:10px"><span class="muted small">📁 โฟลเดอร์ “${esc(cur.folder)}”</span>
        <span class="row right"><a class="btn sm" href="${dl('docx')}">⬇ Word</a><a class="btn sm" href="${dl('pdf')}">⬇ PDF</a>
        ${editable && S.doc.history.length ? '<button id="undo" class="sm" title="ย้อนกลับการแก้ไขล่าสุด">↶ ย้อนกลับ</button>' : ''}</span></div>
      <div class="paperwrap"><div class="paper ${editable ? 'editable' : ''}" id="paper">${S.doc.blocks.map(renderBlock).join('')}</div></div>
      ${editable ? `<div class="chat"><div class="small muted">สั่ง AI ปรับแก้เอกสารนี้ (พิมพ์หรือกด 🎤 พูด) • ชี้ที่ย่อหน้าแล้วกด ✎ เพื่อแก้เอง • ช่องสีเหลืองคือจุดที่ต้องเติมข้อมูลของท่าน</div>
        <div class="chatlog" id="chatlog">${S.chat.map(c => `<div class="${c.role}">${esc(c.text)}</div>`).join('')}</div>
        <div class="chatrow"><textarea id="chatmsg" placeholder="เช่น ขยายความเป็นมาย่อหน้าที่ 2 ให้ละเอียดขึ้น / เพิ่มวัตถุประสงค์ข้อ 3 เรื่องความพึงพอใจ" aria-label="คำสั่งถึง AI"></textarea>
        <button id="mic" title="พูดคำสั่ง" aria-label="พูดคำสั่ง">🎤</button><button id="send" class="primary">ส่ง</button></div></div>`
        : S.doc.editable ? '' : '<p class="small muted">เอกสารนี้ระบบประกอบให้อัตโนมัติจากรายการงานวิจัย จึงแก้ไขโดยเพิ่ม/ลบงานวิจัยในแท็บงานวิจัยที่เกี่ยวข้อง</p>'}`;
    if (editable) bindEditor();
    const first = $('#paper .changed'); if (first) first.scrollIntoView({ block: 'center' });
  }
  $$('.docpills button').forEach(b => (b.onclick = () => { S.docKey = b.dataset.k; S.chat = []; S.changed = []; tabDocs(); }));
}

function renderBlock(b, i) {
  const [k, a, lv] = b;
  const tools = '<span class="tools"><button class="ghost sm" data-act="edit" title="แก้ไข">✎</button><button class="ghost sm danger" data-act="del" title="ลบ">✕</button></span>';
  const wrap = (cls, html) => `<div class="b ${cls} ${S.changed.includes(i) ? 'changed' : ''}" data-i="${i}">${tools}${html}</div>`;
  if (k === 'chapter') return wrap('chapter', `${rich(a)}<br>${rich(lv)}`);
  if (k === 'item') return wrap(`item l${lv || 1}`, rich(a));
  if (k === 'fill') return wrap('', '<div class="fill"></div>'.repeat(a));
  if (k === 'pb' || k === 'blank') return wrap(k, '');
  if (k === 'hd') return wrap('hd', rich(a));
  if (k === 'gantt') {
    const n = a.months.length * 4, cols = [...Array(n).keys()].map(j => j + 1);
    return wrap('tbl gantt', `<table><thead><tr><th rowspan="2">${esc(a.label || 'กิจกรรม')}</th>${a.months.map(m => `<th colspan="4">${esc(m)}</th>`).join('')}</tr>
      <tr>${cols.map(j => `<th>${j <= a.weeks ? j : ''}</th>`).join('')}</tr></thead>
      <tbody>${a.rows.map(([name, s, e]) => `<tr><td>${rich(name)}</td>${cols.map(j => `<td class="${j >= s && j <= e ? 'on' : ''}"></td>`).join('')}</tr>`).join('')}</tbody></table>`);
  }
  if (k === 'sign') {
    return wrap('sign', a.rows.map(r => `<div class="signrow">${r.map(c => c.role ? `<div>${'.'.repeat(44)}<br>(${c.name ? esc(c.name) : '.'.repeat(36)})<br>${esc(c.role)}</div>` : '<div></div>').join('')}</div>`).join(''));
  }
  if (k === 'table') {
    const al = a.align || a.headers.map((_, j) => (j ? 'center' : 'left'));
    const cell = (v, j) => { const bold = String(v).startsWith('!'); const t = rich(bold ? String(v).slice(1) : v);
      return `<td class="${al[j] === 'center' ? 'c' : ''}">${bold ? `<b>${t}</b>` : t}</td>`; };
    return wrap('tbl', `${a.caption ? `<div class="cap">${rich(a.caption).replace(/^(ตารางที่\s*[\d.]+)/, '<b>$1</b>')}</div>` : ''}
      <table><thead><tr>${a.headers.map(h => `<th>${rich(h)}</th>`).join('')}</tr></thead>
      <tbody>${a.rows.map(r => `<tr>${r.map(cell).join('')}</tr>`).join('')}</tbody></table>${a.note ? `<div class="note">${rich(a.note)}</div>` : ''}`);
  }
  return wrap(k, rich(a));
}

function bindEditor() {
  const save = (i, payload) => busy(null, async () => {
    await api(`/projects/${S.pid}/doc/${S.docKey}/block/${i}`, { method: 'POST', body: payload });
    S.doc = null; S.changed = payload.delete ? [] : [i]; await tabDocs();
  });
  $('#paper').onclick = e => {
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const el = btn.closest('.b'), i = +el.dataset.i, b = S.doc.blocks[i];
    if (btn.dataset.act === 'del') return confirm('ลบส่วนนี้?') && save(i, { delete: true });
    const bar = '<div class="row" style="margin:6px 0"><button class="primary sm" data-ok>บันทึก</button><button class="sm" data-no>ยกเลิก</button></div>';
    if (b[0] === 'table') {
      // แก้ไขตาราง: พิมพ์ในเซลล์ได้โดยตรง
      const raw = v => esc(v);
      el.innerHTML = `<label>ชื่อตาราง</label><input data-cap value="${esc(b[1].caption || '')}">
        <table><thead><tr>${b[1].headers.map(h => `<td contenteditable="true" style="font-weight:700">${raw(h)}</td>`).join('')}</tr></thead>
        <tbody>${b[1].rows.map(r => `<tr>${r.map(c => `<td contenteditable="true">${raw(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>
        <div class="row"><button class="sm" data-addrow>+ เพิ่มแถว</button><button class="sm" data-delrow>− ลบแถวสุดท้าย</button></div>${bar}`;
      const tb = $('tbody', el);
      $('[data-addrow]', el).onclick = () => tb.insertAdjacentHTML('beforeend', `<tr>${b[1].headers.map(() => '<td contenteditable="true"></td>').join('')}</tr>`);
      $('[data-delrow]', el).onclick = () => tb.lastElementChild && tb.lastElementChild.remove();
      $('[data-ok]', el).onclick = () => save(i, { block: ['table', { ...b[1], caption: $('[data-cap]', el).value,
        headers: $$('thead td', el).map(c => c.innerText.trim()), rows: $$('tbody tr', el).map(tr => $$('td', tr).map(c => c.innerText.trim())) }] });
    } else if (b[0] === 'gantt') {
      // แผนงาน: แก้ชื่อเดือน ชื่อกิจกรรม และสัปดาห์ที่เริ่ม-สิ้นสุดของแต่ละกิจกรรม
      const row = r => `<tr><td><input data-name value="${esc(r[0])}" aria-label="กิจกรรม"></td><td><input data-s type="number" min="0" max="24" value="${r[1]}" aria-label="สัปดาห์เริ่ม"></td><td><input data-e type="number" min="0" max="24" value="${r[2]}" aria-label="สัปดาห์สิ้นสุด"></td></tr>`;
      el.innerHTML = `<label>เดือน (คั่นด้วยจุลภาค เดือนละ 4 สัปดาห์)</label><input data-months value="${esc(b[1].months.join(', '))}">
        <label>จำนวนสัปดาห์ทั้งหมด</label><input data-weeks type="number" min="1" max="24" value="${b[1].weeks}" style="width:120px">
        <table class="plain"><thead><tr><th>กิจกรรม</th><th style="width:110px">สัปดาห์เริ่ม</th><th style="width:110px">สัปดาห์สิ้นสุด</th></tr></thead><tbody>${b[1].rows.map(row).join('')}</tbody></table>
        <div class="row"><button class="sm" data-addrow>+ เพิ่มกิจกรรม</button><button class="sm" data-delrow>− ลบกิจกรรมสุดท้าย</button></div>${bar}`;
      const tb = $('tbody', el);
      $('[data-addrow]', el).onclick = () => tb.insertAdjacentHTML('beforeend', row(['', 1, 1]));
      $('[data-delrow]', el).onclick = () => tb.lastElementChild && tb.lastElementChild.remove();
      $('[data-ok]', el).onclick = () => save(i, { block: ['gantt', { ...b[1], weeks: +$('[data-weeks]', el).value || 18,
        months: $('[data-months]', el).value.split(',').map(s => s.trim()).filter(Boolean),
        rows: $$('tbody tr', el).map(tr => [$('[data-name]', tr).value, +$('[data-s]', tr).value, +$('[data-e]', tr).value]) }] });
    } else if (b[0] === 'sign') {
      const cells = b[1].rows.flat();
      el.innerHTML = `<div class="small muted">ชื่อที่เว้นว่างจะแสดงเป็นเส้นประให้เขียนเอง • ลบตำแหน่งออกเพื่อเว้นช่องนั้นว่าง</div>
        <div class="grid2">${cells.map(c => `<div data-cell><label>ตำแหน่ง</label><input data-role value="${esc(c.role)}"><label>ชื่อ-สกุล</label><input data-name value="${esc(c.name)}"></div>`).join('')}</div>${bar}`;
      $('[data-ok]', el).onclick = () => { const all = $$('[data-cell]', el).map(d => ({ name: $('[data-name]', d).value, role: $('[data-role]', d).value }));
        save(i, { block: ['sign', { rows: all.reduce((rows, c, j) => (j % 2 ? rows.at(-1).push(c) : rows.push([c]), rows), []) }] }); };
    } else if (b[0] === 'fill') {
      el.innerHTML = `<label>จำนวนบรรทัดเส้นประ</label><input type="number" min="1" max="15" value="${b[1]}" data-n>
        <label>หรือพิมพ์เนื้อหาแทนเส้นประ</label><textarea data-t></textarea>${bar}`;
      $('[data-ok]', el).onclick = () => { const t = $('[data-t]', el).value.trim(); save(i, { block: t ? ['p', t] : ['fill', +$('[data-n]', el).value || 3] }); };
    } else if (b[0] === 'chapter' || b[0] === 'pb' || b[0] === 'blank') { return toast('ส่วนนี้แก้ไขไม่ได้ (ลบได้)');
    } else {
      el.innerHTML = `<textarea data-t>${esc(b[1])}</textarea><div class="small muted">**ตัวหนา** *ตัวเอียง* ⟦ช่องเติมข้อมูล⟧</div>${bar}`;
      $('[data-t]', el).focus();
      $('[data-ok]', el).onclick = () => save(i, { block: [b[0], $('[data-t]', el).value, b[2]].filter(v => v !== undefined) });
    }
    $('[data-no]', el).onclick = () => tabDocs();
  };
  if ($('#undo')) $('#undo').onclick = e => busy(e.target, async () => {
    await api(`/projects/${S.pid}/doc/${S.docKey}/undo`, { method: 'POST' }); S.doc = null; S.changed = []; toast('ย้อนกลับแล้ว'); await tabDocs();
  });
  const send = () => busy($('#send'), async () => {
    const message = $('#chatmsg').value.trim(); if (!message) return;
    const history = S.chat.slice(-8);
    S.chat.push({ role: 'user', text: message });
    try {
      const r = await api(`/projects/${S.pid}/doc/${S.docKey}/chat`, { method: 'POST', body: { message, history } });
      S.chat.push({ role: 'ai', text: r.reply || 'แก้ไขแล้ว' }); S.changed = r.changed; S.doc = null;
    } catch (e) { S.chat.push({ role: 'ai', text: '⚠ ' + e.message }); }
    await tabDocs(); const cl = $('#chatlog'); if (cl) cl.scrollTop = cl.scrollHeight;
  });
  $('#send').onclick = send;
  $('#chatmsg').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition, mic = $('#mic');
  if (!SR) { mic.disabled = true; mic.title = 'เบราว์เซอร์นี้ไม่รองรับการพูด (ใช้ Chrome หรือ Edge)'; return; }
  let rec = null;
  mic.onclick = () => {
    if (rec) return rec.stop();
    rec = new SR(); rec.lang = 'th-TH'; rec.interimResults = true;
    const base = $('#chatmsg').value;
    rec.onresult = ev => { $('#chatmsg').value = (base ? base + ' ' : '') + [...ev.results].map(r => r[0].transcript).join(''); };
    rec.onend = () => { rec = null; mic.classList.remove('rec'); };
    rec.onerror = ev => toast('ใช้ไมโครโฟนไม่ได้: ' + ev.error, true);
    mic.classList.add('rec'); rec.start();
  };
}

// ---- แท็บงานวิจัยที่เกี่ยวข้อง
async function tabPapers() {
  const el = $('#tab'), can = S.proj.can_edit && !S.status.running;
  el.innerHTML = '<p class="boot">กำลังโหลด…</p>';
  const { papers } = await api(`/projects/${S.pid}/papers`);
  if (S.tab !== 'papers') return;
  const need = S.meta.min_papers;
  const sm = [['objective', 'วัตถุประสงค์'], ['sample', 'กลุ่มตัวอย่าง'], ['method', 'วิธีวิจัย'], ['instruments', 'เครื่องมือ/สถิติ'], ['findings', 'ผลการวิจัย']];
  el.innerHTML = `<div class="msg ${papers.length >= need ? 'ok' : 'warn'}">มีไฟล์งานวิจัยฉบับเต็ม ${papers.length} เรื่อง (ต้องมีอย่างน้อย ${need} เรื่อง) — บทที่ 1–3 อ้างอิงได้เฉพาะงานวิจัยในรายการนี้เท่านั้น</div>
    ${can ? `<div class="row"><label class="btn" style="margin:0">⬆ อัปโหลดไฟล์ PDF<input type="file" id="up" accept="application/pdf" class="hidden"></label>
      <input id="purl" placeholder="หรือวางลิงก์หน้าบทความ/ไฟล์ PDF (เช่น จาก ThaiJO)" style="flex:1;min-width:220px" aria-label="ลิงก์งานวิจัย"><button id="addurl">เพิ่มจากลิงก์</button></div>
      <p class="small muted">ระบบจะอ่านไฟล์เพื่อสรุปและจัดรูปแบบอ้างอิงให้ (ประมาณ 20–40 วินาที) หลังเพิ่ม/ลบ ให้กด ↻ เขียนบทที่เกี่ยวข้องใหม่หากต้องการให้เนื้อหาอ้างอิงตามรายการล่าสุด</p>` : ''}
    <ol class="paperlist">${papers.map(p => `<li><div class="row" style="align-items:flex-start"><div style="flex:1;min-width:0">
        <div class="apa">${rich(p.apa)}</div>
        <div class="small muted">อ้างอิงในเนื้อหา: (${esc(p.cite)}) · แหล่ง: ${esc(p.source)} · ${p.summary.pages || '?'} หน้า</div></div>
        <a class="btn sm" href="/api/projects/${S.pid}/papers/${p.id}/file" target="_blank" rel="noopener">เปิด PDF</a>
        ${can ? `<button class="sm danger" data-del="${p.id}">ลบ</button>` : ''}</div>
      <details><summary>สรุปสาระสำคัญ</summary><dl class="kv">${sm.filter(([k]) => p.summary[k]).map(([k, v]) => `<dt>${v}</dt><dd>${esc(p.summary[k])}</dd>`).join('')}</dl></details></li>`).join('')}</ol>
    ${papers.length ? '' : '<div class="empty">ยังไม่มีงานวิจัย ระบบจะค้นและดาวน์โหลดให้ในขั้นตอนที่ 1</div>'}`;
  if (!can) return;
  const done = () => { toast('เพิ่มงานวิจัยแล้ว'); poll(); tabPapers(); };
  $('#up').onchange = e => { const f = e.target.files[0]; if (!f) return; const form = new FormData(); form.append('file', f);
    busy(e.target.closest('label'), async () => { await api(`/projects/${S.pid}/papers/upload`, { method: 'POST', form }); done(); }).then(() => S.tab === 'papers' && tabPapers()); };
  $('#addurl').onclick = e => busy(e.target, async () => { await api(`/projects/${S.pid}/papers/url`, { method: 'POST', body: { url: $('#purl').value } }); done(); });
  $$('[data-del]').forEach(b => (b.onclick = () => confirm('ลบงานวิจัยนี้ออกจากงาน (รวมไฟล์ PDF)?') && busy(b, async () => {
    await api(`/projects/${S.pid}/papers/${b.dataset.del}`, { method: 'DELETE' }); poll(); tabPapers();
  })));
}

// ---- แท็บข้อมูลงาน (requirement + แผนที่ AI วิเคราะห์)
async function tabInfo() {
  const p = S.proj.project, plan = p.plan || {}, can = S.proj.can_edit && !S.status.running;
  const student = p.kind === 'student_project';
  const list = v => (Array.isArray(v) ? v : v ? [v] : []).join('\n');
  const rows = [['research_type', 'ประเภท/รูปแบบของงาน', 1], ['design', 'แบบแผน/วิธีดำเนินการ', 2], ['objectives', 'วัตถุประสงค์ (บรรทัดละ 1 ข้อ)', 4, 1],
    ['hypotheses', 'สมมติฐาน (บรรทัดละ 1 ข้อ)', 3, 1], ['independent_var', 'ตัวแปรต้น', 1], ['dependent_vars', 'ตัวแปรตาม (บรรทัดละ 1 ตัว)', 2, 1],
    ['population', 'ประชากร', 2], ['sample', 'กลุ่มตัวอย่าง/กลุ่มเป้าหมาย', 2], ['innovation', 'นวัตกรรม/สิ่งที่พัฒนา', 1],
    ['instruments', 'เครื่องมือ (บรรทัดละ 1 รายการ)', 3, 1], ['statistics', 'สถิติที่ใช้ (บรรทัดละ 1 รายการ)', 3, 1],
    ['keywords_th', 'คำค้นภาษาไทย (บรรทัดละ 1 วลี)', 3, 1], ['keywords_en', 'คำค้นภาษาอังกฤษ (บรรทัดละ 1 ชุด)', 2, 1]];
  const dis = can ? '' : 'disabled';
  let teachers = [];
  if (can && student) { try { teachers = (await api('/teachers')).teachers; } catch { /* แสดงฟอร์มโดยไม่มีรายชื่อครู */ } }
  if (S.tab !== 'info') return;
  const started = S.status.steps.some(s => s.status === 'done');
  $('#tab').innerHTML = `${S.proj.can_edit ? (S.status.running ? '<div class="msg warn">ระบบกำลังทำงานอยู่ จึงแก้ไขข้อมูลยังไม่ได้ รอให้เสร็จหรือกดยกเลิกก่อน</div>' : '')
      : '<div class="msg info">งานนี้เป็นของผู้อื่น ท่านดูข้อมูลได้แต่แก้ไขไม่ได้</div>'}
    <form id="freq"><h3>ข้อมูลที่กรอกไว้ (Requirement) <span class="muted small">${can ? '— แก้ไขได้ทุกเมื่อ' : ''}</span></h3>
    <fieldset ${dis} style="border:0;padding:0;margin:0">${reqForm(p.requirement, p.kind)}
    ${can && student ? `<label for="advisor_id">ครูที่ปรึกษา</label><select id="advisor_id"><option value="">— ไม่ระบุ —</option>${teachers.filter(t => t.id !== S.user.id)
      .map(t => `<option value="${t.id}" ${t.id === p.advisor_id ? 'selected' : ''}>${esc(t.full_name)}${t.org ? ' · ' + esc(t.org) : ''}</option>`).join('')}</select>` : ''}</fieldset>
    ${can ? `<div class="row" style="margin-top:14px"><button class="primary" data-mode="save">บันทึกการแก้ไข</button>
      <button data-mode="rerun">${started ? 'บันทึกและให้ระบบทำใหม่ทั้งหมด' : 'บันทึกและเริ่มดำเนินการ'}</button></div>
      <p class="small muted">“บันทึกการแก้ไข” เก็บข้อมูลไว้โดยไม่แตะเนื้อหาที่เขียนแล้ว • ${started ? '“ทำใหม่ทั้งหมด” วิเคราะห์ requirement ใหม่และเขียนทุกบทแทนของเดิม (งานวิจัยที่ดาวน์โหลดไว้ยังอยู่)' : 'ระบบจะเริ่มตั้งแต่ขั้นวิเคราะห์ requirement'}</p>` : ''}</form>
    <hr style="border:0;border-top:1px solid var(--line);margin:22px 0">
    <form id="fplan"><h3>หัวข้อและแผนของงาน <span class="muted small">(AI วิเคราะห์จาก requirement${can ? ' — แก้ไขได้ แล้วกด ↻ ที่บทที่ต้องการเพื่อเขียนใหม่' : ''})</span></h3>
    ${Object.keys(plan).length ? '' : '<div class="msg info">ยังไม่มีแผน ระบบจะสร้างให้ในขั้นตอนแรก</div>'}
    <label for="title_th">ชื่อเรื่อง (ไทย)</label><textarea id="title_th" rows="2" ${dis}>${esc(S.status.title_th)}</textarea>
    <label for="title_en">ชื่อเรื่อง (อังกฤษ)</label><textarea id="title_en" rows="2" ${dis}>${esc(S.status.title_en)}</textarea>
    <div class="grid2">${rows.map(([k, label, r]) => `<div><label for="pl_${k}">${label}</label><textarea id="pl_${k}" rows="${r}" style="min-height:0" ${dis}>${esc(list(plan[k]))}</textarea></div>`).join('')}</div>
    ${can ? '<button class="primary" style="margin-top:12px">บันทึกแผน</button>' : ''}</form>`;
  if (!can) return;
  const reload = async () => { S.proj = await api(`/projects/${S.pid}`); S.status = S.proj.status; renderStatus(); };
  $('#fplan').onsubmit = e => { e.preventDefault(); busy(e.submitter, async () => {
    const pl = {}; rows.forEach(([k, , , arr]) => { const v = $('#pl_' + k).value.trim(); pl[k] = arr ? v.split('\n').map(s => s.trim()).filter(Boolean) : v; });
    await api(`/projects/${S.pid}`, { method: 'PATCH', body: { title_th: $('#title_th').value, title_en: $('#title_en').value, plan: pl } });
    await reload(); toast('บันทึกแผนแล้ว — กด ↻ ที่บทที่ต้องการเพื่อเขียนใหม่ตามแผนนี้');
  }); };
  $('#freq').onsubmit = e => { e.preventDefault();
    const rerun = e.submitter.dataset.mode === 'rerun';
    if (rerun && started && !confirm('ให้ระบบวิเคราะห์ requirement ใหม่และเขียนทุกบทแทนของเดิม?\n(ย้อนกลับแต่ละบทได้ด้วยปุ่ม ↶ ในหน้าเอกสาร)')) return;
    busy(e.submitter, async () => {
      const body = { requirement: readReq() };
      if ($('#advisor_id')) body.advisor_id = $('#advisor_id').value || null;
      await api(`/projects/${S.pid}`, { method: 'PATCH', body });
      if (rerun) await api(`/projects/${S.pid}/run`, { method: 'POST', body: { from: 'plan' } });
      await reload();
      toast(rerun ? 'บันทึกแล้ว ระบบกำลังดำเนินการ ดูความคืบหน้าที่แผงขั้นตอน' : 'บันทึกการแก้ไขแล้ว');
      if (rerun) { S.tab = 'docs'; S.doc = null; }
      renderTabs();
    }); };
}

// ---- แท็บความคิดเห็น
async function tabComments() {
  const el = $('#tab');
  el.innerHTML = '<p class="boot">กำลังโหลด…</p>';
  const { comments } = await api(`/projects/${S.pid}/comments`);
  if (S.tab !== 'comments') return;
  const title = k => (S.status.docs.find(d => d.key === k) || {}).title;
  el.innerHTML = `<p class="muted small">พื้นที่สื่อสารระหว่างผู้จัดทำกับครูที่ปรึกษา</p>
    ${comments.map(c => `<div class="comment"><div class="row small"><b>${esc(c.full_name)}</b><span class="badge gray">${esc(S.meta.roles[c.role])}</span>
      ${c.doc_key ? `<span class="badge">${esc(title(c.doc_key))}</span>` : ''}<span class="muted">${esc(c.created_at.slice(0, 16))}</span>
      ${c.user_id === S.user.id || S.user.role === 'admin' ? `<button class="ghost sm danger right" data-del="${c.id}">ลบ</button>` : ''}</div><p>${esc(c.text)}</p></div>`).join('') || '<div class="empty">ยังไม่มีความคิดเห็น</div>'}
    <form id="fc" style="margin-top:14px"><div class="row"><select id="cdoc" style="width:auto" aria-label="เอกสารที่กล่าวถึง"><option value="">ทั้งงาน</option>${S.status.docs.map(d => `<option value="${d.key}">${esc(d.title)}</option>`).join('')}</select></div>
    <textarea id="ctext" required placeholder="พิมพ์ความคิดเห็นหรือข้อเสนอแนะ" style="margin-top:8px" aria-label="ความคิดเห็น"></textarea>
    <button class="primary" style="margin-top:8px">ส่งความคิดเห็น</button></form>`;
  $('#fc').onsubmit = e => { e.preventDefault(); busy(e.submitter, async () => {
    await api(`/projects/${S.pid}/comments`, { method: 'POST', body: { text: $('#ctext').value, doc_key: $('#cdoc').value } }); tabComments();
  }); };
  $$('[data-del]', el).forEach(b => (b.onclick = () => busy(b, async () => { await api(`/projects/${S.pid}/comments/${b.dataset.del}`, { method: 'DELETE' }); tabComments(); })));
}

// ------------------------------------------------------------------ ผู้ดูแลระบบ
async function viewAdmin() {
  shell('<p class="boot">กำลังโหลด…</p>', 'admin');
  const [{ users }, s] = await Promise.all([api('/admin/users'), api('/admin/settings')]);
  const opt = (map, cur) => Object.entries(map).map(([k, v]) => `<option value="${k}" ${k === cur ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const statuses = { active: 'ใช้งาน', pending: 'รออนุมัติ', disabled: 'ระงับ' };
  shell(`<div class="page-head"><h1>ผู้ดูแลระบบ</h1><span class="right muted">ผู้ใช้ ${s.stats.users} · งาน ${s.stats.projects} · ไฟล์งานวิจัย ${s.stats.papers}</span></div>
    <div class="card" style="margin-bottom:16px"><h2 style="font-size:19px">ตั้งค่า AI และระบบ</h2>
      ${s.has_key ? '' : '<div class="msg warn">ยังไม่ได้ตั้งค่า Gemini API key ระบบจะยังสร้างงานวิจัยไม่ได้ — ขอ key ฟรีได้ที่ aistudio.google.com/apikey</div>'}
      <form id="fs"><div class="grid2"><div><label for="api_key">Gemini API key ${s.has_key ? `<span class="muted">(ปัจจุบัน ${esc(s.key_hint)} — เว้นว่างถ้าไม่เปลี่ยน)</span>` : ''}</label><input id="api_key" type="password" autocomplete="off"></div>
        <div><label for="model">โมเดลหลัก <span class="muted">(ใช้เขียนเนื้อหา)</span></label><input id="model" value="${esc(s.model)}"></div>
        <div><label for="fast_model">โมเดลเร็ว/สำรอง <span class="muted">(คัดกรองและอ่านงานวิจัย และใช้แทนเมื่อโมเดลหลักไม่ว่าง)</span></label><input id="fast_model" value="${esc(s.fast_model)}"></div>
        <div><label for="min_interval">เว้นระยะระหว่างคำขอ AI (วินาที) <span class="muted">— เพิ่มค่านี้ถ้าเจอข้อผิดพลาดโควตา 429</span></label><input id="min_interval" type="number" min="0" max="60" step="0.5" value="${s.min_interval}"></div>
        <div><label for="ch2_parallel">เขียนบทที่ 2 พร้อมกันกี่หัวข้อ <span class="muted">— 1 สำหรับ key ฟรี, 3–6 สำหรับ key แบบชำระเงิน (เร็วขึ้นแต่ใช้โควตาต่อนาทีมากขึ้น)</span></label><input id="ch2_parallel" type="number" min="1" max="6" step="1" value="${s.ch2_parallel}"></div>
        <div><label for="allow_register">การสมัครใช้งานด้วยตนเอง</label><select id="allow_register"><option value="1" ${s.allow_register ? 'selected' : ''}>เปิด (ครูต้องรออนุมัติ)</option><option value="0" ${s.allow_register ? '' : 'selected'}>ปิด (ผู้ดูแลสร้างบัญชีให้)</option></select></div></div>
      <h3 style="margin-top:20px;font-size:17px">แบบเสนอโครงงาน — ข้อมูลของสถานศึกษา <span class="muted small">(ใช้เมื่อผู้จัดทำไม่ได้กรอกเอง ชื่อที่เว้นว่างจะเป็นเส้นประในช่องลงนาม)</span></h3>
      <div class="grid2">${[['institution', 'พื้นที่ดำเนินการ (ชื่อสถานศึกษา)'], ['department', 'แผนกวิชา (ค่าเริ่มต้น)'], ['subject_teacher', 'ครูประจำวิชา'], ['head', 'หัวหน้าแผนกวิชา'], ['deputy', 'รองผู้อำนวยการฝ่ายวิชาการ']]
        .map(([k, label]) => `<div><label for="form_${k}">${label}</label><input id="form_${k}" data-form="${k}" value="${esc(s.form[k] || '')}"></div>`).join('')}</div>
      <div class="row" style="margin-top:14px"><button class="primary">บันทึกการตั้งค่า</button><button type="button" id="test">ทดสอบการเชื่อมต่อ AI</button></div></form></div>
    <div class="card"><div class="row"><h2 style="font-size:19px">ผู้ใช้งาน</h2><button id="addu" class="right sm primary">+ เพิ่มผู้ใช้</button></div>
      <form id="fu" class="hidden" style="margin-top:10px"><div class="grid2">
        <div><label for="nu_full_name">ชื่อ-สกุล</label><input id="nu_full_name" required></div><div><label for="nu_role">บทบาท</label><select id="nu_role">${opt(S.meta.roles, 'student')}</select></div>
        <div><label for="nu_username">อีเมล (ชื่อผู้ใช้)</label><input id="nu_username" type="email" required autocomplete="off"></div><div><label for="nu_password">รหัสผ่านเริ่มต้น</label><input id="nu_password" required autocomplete="off"></div></div>
        <button class="primary" style="margin-top:10px">สร้างบัญชี</button></form>
      <div class="tablewrap"><table class="data" style="margin-top:10px"><thead><tr><th>ชื่อ-สกุล</th><th>อีเมล (ชื่อผู้ใช้)</th><th>บทบาท</th><th>สถานะ</th><th>งาน</th><th></th></tr></thead>
      <tbody>${users.map(u => `<tr data-id="${u.id}"><td>${esc(u.full_name)}<div class="small muted">${esc([u.level, u.group_name && `กลุ่ม ${u.group_name}`, u.org].filter(Boolean).join(' · '))}</div></td><td>${esc(u.username)}</td>
        <td><select data-f="role" aria-label="บทบาท">${opt(S.meta.roles, u.role)}</select></td>
        <td><select data-f="status" aria-label="สถานะ">${opt(statuses, u.status)}</select>${u.status === 'pending' ? ' <span class="badge warn">รออนุมัติ</span>' : ''}</td>
        <td>${u.n_projects}</td><td class="row"><button class="sm" data-pw>ตั้งรหัสผ่านใหม่</button>${u.id === S.user.id ? '' : '<button class="sm danger" data-rm>ลบ</button>'}</td></tr>`).join('')}</tbody></table></div></div>`, 'admin');
  $('#fs').onsubmit = e => { e.preventDefault(); busy(e.submitter, async () => {
    await api('/admin/settings', { method: 'POST', body: { api_key: $('#api_key').value, model: $('#model').value, fast_model: $('#fast_model').value, min_interval: $('#min_interval').value, ch2_parallel: $('#ch2_parallel').value, allow_register: $('#allow_register').value === '1',
      form: Object.fromEntries($$('[data-form]').map(i => [i.dataset.form, i.value])) } });
    S.meta = null; toast('บันทึกแล้ว'); route();
  }); };
  $('#test').onclick = e => busy(e.target, async () => { const r = await api('/admin/settings/test', { method: 'POST' }); toast('เชื่อมต่อ AI สำเร็จ: ' + r.reply); });
  $('#addu').onclick = () => $('#fu').classList.toggle('hidden');
  $('#fu').onsubmit = e => { e.preventDefault(); busy(e.submitter, async () => {
    await api('/admin/users', { method: 'POST', body: Object.fromEntries($$('#fu input, #fu select').map(i => [i.id.slice(3), i.value])) }); toast('สร้างบัญชีแล้ว'); viewAdmin();
  }); };
  $$('tr[data-id]').forEach(tr => {
    const id = tr.dataset.id, patch = body => busy(null, async () => { await api(`/admin/users/${id}`, { method: 'PATCH', body }); toast('บันทึกแล้ว'); }).then(viewAdmin);
    $$('select', tr).forEach(sel => (sel.onchange = () => patch({ [sel.dataset.f]: sel.value })));
    $('[data-pw]', tr).onclick = () => { const pw = prompt('รหัสผ่านใหม่ (อย่างน้อย 8 ตัวอักษร)'); if (pw) patch({ password: pw }); };
    const rm = $('[data-rm]', tr);
    if (rm) rm.onclick = () => confirm('ลบผู้ใช้นี้?') && busy(rm, async () => { await api(`/admin/users/${id}`, { method: 'DELETE' }); viewAdmin(); });
  });
}

route().catch(e => { app.innerHTML = `<p class="boot">เริ่มระบบไม่สำเร็จ: ${esc(e.message)}</p>`; });
