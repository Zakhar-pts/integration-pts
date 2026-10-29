import os, json, sqlite3, secrets, hmac, ipaddress, socket
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlsplit
import requests
from flask import Flask, request, redirect, url_for, session, render_template_string, flash, jsonify, abort
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get('APP_SECRET') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','false').lower()=='true', MAX_CONTENT_LENGTH=1024*1024)
DB = os.environ.get('DATABASE_PATH', os.path.join(os.path.dirname(__file__), 'data', 'flowpilot.db'))
ADMIN = os.environ.get('ADMIN_USERNAME','admin')
PASSWORD = os.environ.get('ADMIN_PASSWORD','')
BASE = os.environ.get('PUBLIC_BASE_URL','http://localhost:8000').rstrip('/')
if not PASSWORD: raise RuntimeError('Set ADMIN_PASSWORD in .env')

def db():
    os.makedirs(os.path.dirname(os.path.abspath(DB)),exist_ok=True)
    c=sqlite3.connect(DB,timeout=30)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        c.execute('''CREATE TABLE IF NOT EXISTS workflows (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, token TEXT UNIQUE NOT NULL, method TEXT NOT NULL DEFAULT 'POST', destination TEXT NOT NULL, headers TEXT NOT NULL DEFAULT '{}', payload TEXT NOT NULL DEFAULT '{{payload}}', enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id INTEGER NOT NULL, timestamp TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, FOREIGN KEY(workflow_id) REFERENCES workflows(id))''')
        if not c.execute("SELECT 1 FROM settings WHERE key='admin_hash'").fetchone():
            c.execute('INSERT INTO settings VALUES (?,?)',('admin_hash',generate_password_hash(PASSWORD)))
init_db()

def authenticated(): return session.get('user')==ADMIN

def login_required(f):
    @wraps(f)
    def wrapped(*args,**kwargs):
        if not authenticated(): return redirect(url_for('login'))
        return f(*args,**kwargs)
    return wrapped

@app.before_request
def csrf_protect():
    if 'csrf' not in session: session['csrf']=secrets.token_urlsafe(32)
    if request.method in ('POST','PUT','PATCH','DELETE') and not request.path.startswith('/hook/'):
        if not hmac.compare_digest(request.form.get('csrf',''),session['csrf']): abort(403)

@app.context_processor
def inject(): return dict(csrf=session.get('csrf'), base=BASE)

CSS='''<style>:root{font-family:Inter,system-ui,-apple-system,sans-serif;color:#e9eafa;background:#0b1020}*{box-sizing:border-box}body{margin:0}a{color:#9fb8ff;text-decoration:none}.shell{display:flex;min-height:100vh}aside{width:230px;background:#111a2e;padding:28px 18px;border-right:1px solid #263047}aside a{display:block;padding:12px;border-radius:10px;color:#adb9d0;margin:9px 0}aside a:hover{background:#23304b;color:#fff}.logo{font-size:24px;font-weight:800;margin-bottom:36px;color:#fff}main{padding:40px;flex:1;max-width:1250px}h1{margin:0 0 8px}p,.muted{color:#9caac4}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px;gap:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.card{background:#151f34;border:1px solid #2b3955;border-radius:15px;padding:22px}.num{font-size:32px;font-weight:800;color:#fff}button,.btn{background:#657dff;color:#fff;border:0;padding:11px 17px;border-radius:9px;font-weight:700;cursor:pointer;display:inline-block}button.secondary,.btn.secondary{background:#293953}input,textarea,select{width:100%;background:#0f172a;color:#fff;border:1px solid #405070;padding:12px;border-radius:8px;margin:7px 0 18px;font:inherit}textarea{min-height:115px}label{font-weight:650;font-size:14px}table{width:100%;border-collapse:collapse}td,th{padding:15px 12px;text-align:left;border-bottom:1px solid #2b3955}th{color:#9caac4;font-size:13px}.tag{border-radius:20px;padding:5px 10px;background:#1a654e;color:#b4f6d5;font-size:12px}.off{background:#5a3542;color:#ffd5df}.notice{padding:12px 16px;background:#283a60;border-radius:8px;margin-bottom:18px}.mono{font-family:monospace;overflow-wrap:anywhere}.steps{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.step{border:1px solid #3e4f77;padding:14px;border-radius:10px;background:#202c46}@media(max-width:760px){.shell{display:block}aside{width:100%;padding:16px}aside a{display:inline-block}.logo{margin:0}main{padding:18px}} </style>'''
LAYOUT='''<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FlowPilot</title>'''+CSS+'''</head><body><div class="shell"><aside><div class="logo">◈ FlowPilot</div><div class="muted">Особиста автоматизація</div><a href="{{url_for('index')}}">▦ Огляд</a><a href="{{url_for('new_workflow')}}">＋ Новий сценарій</a><a href="{{url_for('history')}}">◷ Історія запусків</a><form method="post" action="{{url_for('logout')}}"><input type="hidden" name="csrf" value="{{csrf}}"><button class="secondary" style="margin-top:20px">Вийти</button></form></aside><main>{% with msgs=get_flashed_messages() %}{% for m in msgs %}<div class="notice">{{m}}</div>{% endfor %}{% endwith %}{{body|safe}}</main></div></body></html>'''

def page(template,**kwargs):
    from flask import render_template_string as render
    body=render(template,**kwargs)
    return render(LAYOUT,body=body)

LOGIN='''<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'''+CSS+'''</head><body><div class="card" style="max-width:420px;margin:12vh auto"><h1>◈ FlowPilot</h1><p>Приватний кабінет інтеграцій</p>{% with msgs=get_flashed_messages() %}{% for m in msgs %}<div class="notice">{{m}}</div>{% endfor %}{% endwith %}<form method="post"><input type="hidden" name="csrf" value="{{csrf}}"><label>Логін</label><input name="username" required><label>Пароль</label><input type="password" name="password" required><button style="width:100%">Увійти</button></form></div></body></html>'''
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        with db() as c: row=c.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()
        if hmac.compare_digest(request.form.get('username',''),ADMIN) and check_password_hash(row['value'],request.form.get('password','')):
            session.clear(); session['user']=ADMIN; session['csrf']=secrets.token_urlsafe(32)
            return redirect(url_for('index'))
        flash('Неправильний логін або пароль')
    return render_template_string(LOGIN)

@app.post('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

INDEX='''<div class="top"><div><h1>Панель керування</h1><p>Усі автоматизації під твоїм контролем.</p></div><a class="btn" href="{{url_for('new_workflow')}}">+ Створити сценарій</a></div><div class="grid"><div class="card"><div class="muted">Усього сценаріїв</div><div class="num">{{stats.total}}</div></div><div class="card"><div class="muted">Активні</div><div class="num">{{stats.active}}</div></div><div class="card"><div class="muted">Запусків</div><div class="num">{{stats.runs}}</div></div></div><h2 style="margin-top:35px">Мої інтеграції</h2><div class="card">{% if items %}<table><thead><tr><th>Назва</th><th>Маршрут</th><th>Статус</th><th>Дії</th></tr></thead><tbody>{% for i in items %}<tr><td><b>{{i.name}}</b></td><td>Webhook → HTTP {{i.method}}</td><td><span class="tag {{'off' if not i.enabled}}">{{'Увімкнено' if i.enabled else 'Вимкнено'}}</span></td><td><a href="{{url_for('edit_workflow',wid=i.id)}}">Відкрити →</a></td></tr>{% endfor %}</tbody></table>{% else %}<p>Сценаріїв поки немає. Створи першу інтеграцію.</p>{% endif %}</div>'''
@app.get('/')
@login_required
def index():
    with db() as c:
        items=c.execute('SELECT * FROM workflows ORDER BY id DESC').fetchall()
        stats=dict(total=c.execute('SELECT count(*) FROM workflows').fetchone()[0],active=c.execute('SELECT count(*) FROM workflows WHERE enabled=1').fetchone()[0],runs=c.execute('SELECT count(*) FROM runs').fetchone()[0])
    return page(INDEX,items=items,stats=stats)

EDITOR='''<div class="top"><div><h1>{{'Редагувати сценарій' if item else 'Новий сценарій'}}</h1><p>Вебхук запускає HTTP-запит до обраного сервісу.</p></div><a class="btn secondary" href="{{url_for('index')}}">← Назад</a></div><div class="steps"><div class="step">⚡ Вхідний Webhook</div><span>→</span><div class="step">⇄ Підстановка полів</div><span>→</span><div class="step">↗ HTTP-дія</div></div><form method="post" class="card" style="max-width:900px;margin-top:22px"><input type="hidden" name="csrf" value="{{csrf}}"><label>Назва інтеграції</label><input name="name" value="{{item.name if item else ''}}" placeholder="Заявки з сайту → CRM" required maxlength="120"><label>URL сервісу-отримувача (тільки HTTPS)</label><input name="destination" type="url" value="{{item.destination if item else ''}}" placeholder="https://api.example.com/v1/leads" required><label>HTTP-метод</label><select name="method">{% for m in ['POST','PUT','PATCH'] %}<option value="{{m}}" {{'selected' if item and item.method==m}}>{{m}}</option>{% endfor %}</select><label>Заголовки HTTP (JSON; наприклад, Authorization)</label><textarea name="headers" spellcheck="false">{{item.headers if item else '{"Content-Type": "application/json"}'}}</textarea><label>Шаблон тіла запиту (JSON, доступні {{'{{payload}}'}} та {{'{{payload.field}}'}})</label><textarea name="payload" spellcheck="false">{{item.payload if item else '{"name":"{{payload.name}}","email":"{{payload.email}}"}'}}</textarea><label><input type="checkbox" name="enabled" style="width:auto;margin:12px" {{'checked' if not item or item.enabled}}> Активний сценарій</label><div><button>Зберегти інтеграцію</button></div></form>{% if item %}<div class="card" style="max-width:900px;margin-top:18px"><h2>Webhook URL</h2><div class="mono">{{base}}/hook/{{item.token}}</div><p>Надішли POST-запит з JSON. Токен у URL є секретним — не публікуй його.</p><form method="post" action="{{url_for('manual_run',wid=item.id)}}"><input type="hidden" name="csrf" value="{{csrf}}"><label>Тестові дані (JSON)</label><textarea name="data">{"name":"Тестовий клієнт","email":"test@example.com"}</textarea><button>▶ Тестовий запуск</button></form><form method="post" action="{{url_for('delete_workflow',wid=item.id)}}" onsubmit="return confirm('Видалити сценарій?')" style="margin-top:22px"><input type="hidden" name="csrf" value="{{csrf}}"><button class="secondary">Видалити сценарій</button></form></div>{% endif %}'''

def validate_destination(url):
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443): raise ValueError('Потрібна HTTPS-адреса без логіна, пароля та нестандартного порту')
    addresses=socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
    if not addresses: raise ValueError('Не вдалося знайти адресу')
    for addr in addresses:
        ip=ipaddress.ip_address(addr[4][0])
        if not ip.is_global: raise ValueError('Локальні та приватні адреси заборонені')
    return url

def form_values():
    name=request.form.get('name','').strip()[:120]
    if not name: raise ValueError('Вкажи назву')
    destination=validate_destination(request.form.get('destination','').strip())
    method=request.form.get('method','POST')
    if method not in ('POST','PUT','PATCH'): raise ValueError('Недозволений HTTP метод')
    headers=request.form.get('headers','{}'); payload=request.form.get('payload','{}')
    h=json.loads(headers); json.loads(payload)
    if not isinstance(h,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in h.items()): raise ValueError('Заголовки мають бути JSON-об’єктом рядків')
    if any(k.lower() in ('host','content-length','transfer-encoding','connection') for k in h): raise ValueError('Заборонений системний заголовок')
    return (name,method,destination,headers,payload,1 if request.form.get('enabled') else 0)

@app.route('/workflows/new',methods=['GET','POST'])
@login_required
def new_workflow():
    if request.method=='POST':
        try:
            vals=form_values()
            with db() as c:
                cur=c.execute('INSERT INTO workflows(name,method,destination,headers,payload,enabled,token,created_at) VALUES (?,?,?,?,?,?,?,?)',(*vals,secrets.token_urlsafe(32),datetime.now(timezone.utc).isoformat()))
                wid=cur.lastrowid
            flash('Інтеграцію створено'); return redirect(url_for('edit_workflow',wid=wid))
        except (ValueError,json.JSONDecodeError,OSError) as e: flash('Помилка: '+str(e))
    return page(EDITOR,item=None)

@app.route('/workflows/<int:wid>',methods=['GET','POST'])
@login_required
def edit_workflow(wid):
    with db() as c: item=c.execute('SELECT * FROM workflows WHERE id=?',(wid,)).fetchone()
    if not item: abort(404)
    if request.method=='POST':
        try:
            vals=form_values()
            with db() as c: c.execute('UPDATE workflows SET name=?,method=?,destination=?,headers=?,payload=?,enabled=? WHERE id=?',(*vals,wid))
            flash('Зміни збережено');return redirect(url_for('edit_workflow',wid=wid))
        except (ValueError,json.JSONDecodeError,OSError) as e: flash('Помилка: '+str(e))
    return page(EDITOR,item=item)

@app.post('/workflows/<int:wid>/delete')
@login_required
def delete_workflow(wid):
    with db() as c:
        c.execute('DELETE FROM runs WHERE workflow_id=?',(wid,))
        c.execute('DELETE FROM workflows WHERE id=?',(wid,))
    flash('Сценарій видалено');return redirect(url_for('index'))

def interpolate(obj, data):
    if isinstance(obj,dict): return {k:interpolate(v,data) for k,v in obj.items()}
    if isinstance(obj,list): return [interpolate(v,data) for v in obj]
    if not isinstance(obj,str): return obj
    if obj=='{{payload}}': return data
    if obj.startswith('{{payload.') and obj.endswith('}}'):
        key=obj[10:-2];return data.get(key,'') if isinstance(data,dict) else ''
    import re
    return re.sub(r'\{\{payload\.([a-zA-Z0-9_]+)\}\}',lambda m:str(data.get(m.group(1),'')) if isinstance(data,dict) else '',obj)

def run_workflow(item,data,source):
    status='success'; detail=''
    try:
        # Re-resolve at dispatch. Production deployments should add egress firewall or DNS-pinned transport.
        validate_destination(item['destination'])
        headers=json.loads(item['headers']); body=interpolate(json.loads(item['payload']),data)
        # No redirects to unvalidated destinations.
        r=requests.request(item['method'],item['destination'],json=body,headers=headers,timeout=12,allow_redirects=False)
        r.raise_for_status();detail=f'HTTP {r.status_code}'
    except Exception as e:
        status='error';detail=str(e)[:450]
    with db() as c: c.execute('INSERT INTO runs(workflow_id,timestamp,source,status,detail) VALUES(?,?,?,?,?)',(item['id'],datetime.now(timezone.utc).isoformat(),source,status,detail))
    return status,detail

@app.post('/hook/<token>')
def webhook(token):
    with db() as c: item=c.execute('SELECT * FROM workflows WHERE token=? AND enabled=1',(token,)).fetchone()
    if not item: abort(404)
    data=request.get_json(silent=True)
    if not isinstance(data,(dict,list)): return jsonify(error='JSON object or array required'),400
    status,detail=run_workflow(item,data,'webhook')
    return jsonify(status=status,detail=detail),200 if status=='success' else 502

@app.post('/workflows/<int:wid>/run')
@login_required
def manual_run(wid):
    with db() as c: item=c.execute('SELECT * FROM workflows WHERE id=?',(wid,)).fetchone()
    if not item: abort(404)
    try:
        data=json.loads(request.form.get('data','{}'))
        status,detail=run_workflow(item,data,'manual')
        flash(f'Тест: {status} — {detail}')
    except ValueError as e: flash('Некоректний JSON: '+str(e))
    return redirect(url_for('edit_workflow',wid=wid))

HISTORY='''<div class="top"><div><h1>Історія запусків</h1><p>Останні 100 виконань. Час у UTC.</p></div></div><div class="card">{% if runs %}<table><thead><tr><th>Час</th><th>Сценарій</th><th>Джерело</th><th>Статус</th><th>Деталі</th></tr></thead><tbody>{% for r in runs %}<tr><td class="muted">{{r.timestamp[:19]}}</td><td>{{r.name}}</td><td>{{r.source}}</td><td><span class="tag {{'off' if r.status=='error'}}">{{r.status}}</span></td><td class="mono">{{r.detail}}</td></tr>{% endfor %}</tbody></table>{% else %}<p>Поки немає запусків.</p>{% endif %}</div>'''
@app.get('/history')
@login_required
def history():
    with db() as c: runs=c.execute('SELECT r.*,w.name FROM runs r JOIN workflows w ON r.workflow_id=w.id ORDER BY r.id DESC LIMIT 100').fetchall()
    return page(HISTORY,runs=runs)

@app.get('/health')
def health():return jsonify(ok=True)
if __name__=='__main__': app.run(port=8000,debug=False)
