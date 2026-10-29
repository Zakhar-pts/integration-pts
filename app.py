import os, json, secrets, hmac, re, ipaddress, socket
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse
import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, request, session, redirect, url_for, abort, flash, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

app=Flask(__name__)
app.secret_key=os.environ.get('APP_SECRET') or secrets.token_urlsafe(48)
app.config['SESSION_COOKIE_HTTPONLY']=True
app.config['SESSION_COOKIE_SAMESITE']='Lax'
app.config['SESSION_COOKIE_SECURE']=os.environ.get('COOKIE_SECURE','false').lower()=='true'
app.config['MAX_CONTENT_LENGTH']=1024*1024
rawdb=os.environ.get('DATABASE_URL','sqlite:////app/data/flowpilot.db')
if rawdb.startswith('postgres://'): rawdb='postgresql+psycopg://'+rawdb[len('postgres://'):]
if rawdb.startswith('postgresql://'): rawdb='postgresql+psycopg://'+rawdb[len('postgresql://'):]
app.config['SQLALCHEMY_DATABASE_URI']=rawdb
app.config['SQLALCHEMY_TRACK_MODIFICATIONS']=False
app.config['SQLALCHEMY_ENGINE_OPTIONS']={'pool_pre_ping':True}
db=SQLAlchemy(app)
ADMIN=os.environ.get('ADMIN_USERNAME','admin')
PASSWORD=os.environ.get('ADMIN_PASSWORD','')
FKEY=os.environ.get('ENCRYPTION_KEY','')
if not PASSWORD: raise RuntimeError('Set ADMIN_PASSWORD in Render Environment')
if not FKEY: raise RuntimeError('Set ENCRYPTION_KEY with a Fernet
key in Render Environment')
fernet=Fernet(FKEY.encode())

class Connection(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(100),nullable=False)
    kind=db.Column(db.String(40),nullable=False)
    secret=db.Column(db.Text,nullable=False)
    created=db.Column(db.DateTime,default=lambda: datetime.now(timezone.utc))

class Workflow(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(160),nullable=False)
    trigger_token=db.Column(db.String(128),unique=True,nullable=False,default=lambda: secrets.token_urlsafe(32))
    action=db.Column(db.String(40),nullable=False)
    connection_id=db.Column(db.Integer,db.ForeignKey('connection.id'),nullable=True)
    config=db.Column(db.Text,nullable=False,default='{}')
    enabled=db.Column(db.Boolean,nullable=False,default=True)
    created=db.Column(db.DateTime,default=lambda: datetime.now(timezone.utc))
    connection=db.relationship('Connection')

class Run(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    workflow_id=db.Column(db.Integer,db.ForeignKey('workflow.id'),nullable=False)
    status=db.Column(db.String(30),nullable=False)
    message=db.Column(db.Text,nullable=False)
    created=db.Column(db.DateTime,default=lambda: datetime.now(timezone.utc))
    workflow=db.relationship('Workflow')

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

CATALOG=[('webhook','Webhook / API','Готовий тригер та універсальний HTTP-запит','ready'),('telegram','Telegram','Надіслати повідомлення через Bot API','ready'),('openai','OpenAI','Виконати запит до Responses API','ready'),('sheets','Google Sheets','Додати рядок у таблицю через OAuth access token','token'),('gmail','Gmail','Надіслати лист через OAuth access token','token'),('facebook','Facebook Pages','Створити допис на сторінці','token'),('instagram','Instagram','Публікація через Instagram Graph API','planned'),('googleads','Google Ads','Підготовлено місце під OAuth + developer token','planned'),('crm','CRM / Custom API','Універсальна передача даних у CRM через HTTP','ready')]

@app.context_processor
def globals_():
    return dict(catalog=CATALOG,username=ADMIN)

def login_required(fn):
    @wraps(fn)
    def inner(*a,**kw):
        if session.get('authenticated') is not True: return redirect(url_for('login'))
        return fn(*a,**kw)
    return inner

def csrf_check():
    if request.method in ('POST','PUT','PATCH','DELETE') and not request.path.startswith('/hook/'):
        supplied=request.form.get('_csrf','')
        if not hmac.compare_digest(supplied,session.get('csrf','')): abort(403)
@app.before_request
def before():
    if 'csrf' not in session: session['csrf']=secrets.token_urlsafe(32)
    csrf_check()
@app.context_processor
def csrf(): return dict(csrf=session.get('csrf',''))

@app.route('/health')
def health(): return {'status':'ok'}
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        if hmac.compare_digest(request.form.get('username',''),ADMIN) and hmac.compare_digest(request.form.get('password',''),PASSWORD):
            session.clear();session['authenticated']=True;session['csrf']=secrets.token_urlsafe(32)
            return redirect(url_for('dashboard'))
        flash('Неправильний логін або пароль','error')
    return render_template('login.html')
@app.post('/logout')
@login_required
def logout(): session.clear();return redirect(url_for('login'))
@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html',n=Workflow.query.count(),success=Run.query.filter_by(status='success').count(),fails=Run.query.filter_by(status='error').count(),recent=Run.query.order_by(Run.id.desc()).limit(8).all())
@app.route('/catalog')
@login_required
def catalog():return render_template('catalog.html')
@app.route('/connections',methods=['GET','POST'])
@login_required
def connections():
    if request.method=='POST':
        name=request.form.get('name','').strip()[:100];kind=request.form.get('kind','').strip();token=request.form.get('token','').strip()
        if not name or not token or kind not in ('telegram','openai','sheets','gmail','facebook','http'):flash('Заповни поля','error')
        else:
            db.session.add(Connection(name=name,kind=kind,secret=fernet.encrypt(token.encode()).decode()));db.session.commit();flash('Підключення додано','success')
        return redirect(url_for('connections'))
    return render_template('connections.html',items=Connection.query.order_by(Connection.id.desc()).all())
@app.post('/connections/<int:cid>/delete')
@login_required
def connection_delete(cid):
    c=db.get_or_404(Connection,cid)
    if Workflow.query.filter_by(connection_id=cid).first(): flash('Спочатку видали сценарії з цим підключенням','error')
    else:db.session.delete(c);db.session.commit()
    return redirect(url_for('connections'))

def config_for_form(form):
    data={k:form.get(k,'').strip() for k in ('url','method','headers','body','chat_id','prompt','spreadsheet_id','range','to','subject','message','page_id','source')}
    if data['headers']:json.loads(data['headers'])
    return json.dumps(data,ensure_ascii=False)
@app.route('/workflows')
@login_required
def workflows():return render_template('workflows.html',items=Workflow.query.order_by(Workflow.id.desc()).all())
@app.route('/workflows/new',methods=['GET','POST'])
@login_required
def workflow_new():
    if request.method=='POST':
        action=request.form.get('action','http');name=request.form.get('name','').strip()[:160]
        conn_id=request.form.get('connection_id','').strip()
        if action not in ('http','telegram','openai','sheets','gmail','facebook') or not name:flash('Перевір назву й дію','error')
        else:
            try:
                config=config_for_form(request.form)
                conn=db.session.get(Connection,int(conn_id)) if conn_id else None
                if conn_id and not conn:raise ValueError('Підключення не знайдено')
                obj=Workflow(name=name,action=action,config=config,connection_id=conn.id if conn else None)
                db.session.add(obj);db.session.commit();flash('Сценарій створено','success');return redirect(url_for('workflow_detail',wid=obj.id))
            except (ValueError,TypeError,json.JSONDecodeError) as e:flash(f'Помилка конфігурації: {e}','error')
    return render_template('workflow_form.html',connections=Connection.query.all())
@app.route('/workflows/<int:wid>')
@login_required
def workflow_detail(wid):
    w=db.get_or_404(Workflow,wid)
    return render_template('workflow_detail.html',w=w,cfg=json.loads(w.config),runs=Run.query.filter_by(workflow_id=wid).order_by(Run.id.desc()).limit(20).all())
@app.post('/workflows/<int:wid>/toggle')
@login_required
def workflow_toggle(wid):
    w=db.get_or_404(Workflow,wid);w.enabled=not w.enabled;db.session.commit();return redirect(url_for('workflow_detail',wid=wid))
@app.post('/workflows/<int:wid>/delete')
@login_required
def workflow_delete(wid):
    w=db.get_or_404(Workflow,wid);Run.query.filter_by(workflow_id=wid).delete();db.session.delete(w);db.session.commit();return redirect(url_for('workflows'))

VAR=re.compile(r'{{\s*payload\.([a-zA-Z0-9_.-]+)\s*}}')
def map_text(s,payload):
    def get(m):
        cur=payload
        for p in m.group(1).split('.'):
            if not isinstance(cur,dict):return ''
            cur=cur.get(p,'')
        return str(cur) if not isinstance(cur,(dict,list)) else json.dumps(cur,ensure_ascii=False)
    return VAR.sub(get,str(s))
def mapped_body(raw,payload):
    s=map_text(raw or '{}',payload)
    try:return json.loads(s)
    except ValueError:raise ValueError('Некоректний JSON після підстановки полів')

def validate_public_url(url):
    p=urlparse(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Потрібен публічний HTTPS URL')
    if p.port not in (None,443):raise ValueError('Дозволений лише HTTPS порт 443')
    for info in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
        ip=ipaddress.ip_address(info[4][0]);
        if not ip.is_global:raise ValueError('Приватні та локальні адреси заборонені')
    # DNS rebinding remains possible between validation and requests. Do not treat this as a hardened SSRF boundary.
    return url

def send(url,method='POST',headers=None,body=None):
    validate_public_url(url)
    try:
        r=requests.request(method,url,headers=headers or {},json=body,timeout=20,allow_redirects=False)
        return r.status_code, r.text[:400]
    except requests.RequestException as e:raise ValueError(f'HTTP-запит не вдався: {str(e)[:180]}')
def execute(w,payload):
    cfg=json.loads(w.config);kind=w.action
    token=fernet.decrypt(w.connection.secret.encode()).decode() if w.connection else ''
    if kind=='http':
        url=map_text(cfg.get('url',''),payload)
        hdr=json.loads(map_text(cfg.get('headers') or '{}',payload))
        if token:hdr['Authorization']='Bearer '+token
        return send(url,cfg.get('method','POST').upper(),hdr,mapped_body(cfg.get('body'),payload))
    if kind=='telegram':
        if not token:raise ValueError('Потрібне підключення Telegram')
        return send('https://api.telegram.org/bot'+token+'/sendMessage',body={'chat_id':map_text(cfg['chat_id'],payload),'text':map_text(cfg['message'],payload)})
    if kind=='openai':
        if not token:raise ValueError('Потрібен ключ OpenAI')
        return send('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+token},body={'model':'gpt-4.1-mini','input':map_text(cfg['prompt'],payload)})
    if kind=='sheets':
        if not token:raise ValueError('Потрібен Google OAuth access token')
        sid=cfg['spreadsheet_id'];rang=cfg.get('range') or 'Sheet1!A:Z'
        if not re.fullmatch(r'[a-zA-Z0-9_-]{15,}',sid):raise ValueError('Некоректний spreadsheet ID')
        from urllib.parse import quote
        url=f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{quote(rang,safe="")}\u003aappend?valueInputOption=USER_ENTERED'
        return send(url,headers={'Authorization':'Bearer '+token},body=mapped_body(cfg.get('body') or '{"values":[["{{payload.name}}"]]}',payload))
    if kind=='gmail':
        if not token:raise ValueError('Потрібен Google OAuth access token')
        from email.message import EmailMessage
        import base64
        msg=EmailMessage();msg['To']=map_text(cfg['to'],payload);msg['Subject']=map_text(cfg['subject'],payload);msg.set_content(map_text(cfg['message'],payload))
        raw=base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return send('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',headers={'Authorization':'Bearer '+token},body={'raw':raw})
    if kind=='facebook':
        if not token:raise ValueError('Потрібен Page access token')
        pid=cfg['page_id']
        if not pid.isdigit():raise ValueError('Некоректний Page ID')
        return send('https://graph.facebook.com/v23.0/'+pid+'/feed',headers={'Authorization':'Bearer '+token},body={'message':map_text(cfg['message'],payload)})
    raise ValueError('Невідома дія')

def run_workflow(w,payload):
    if not w.enabled:return {'error':'Сценарій вимкнено'},409
    try:
        code,message=execute(w,payload);ok=200<=code<300
        status='success' if ok else 'error'
        # Do not store response bodies: APIs can return sensitive user data.
        db.session.add(Run(workflow_id=w.id,status=status,message=f'HTTP {code}'))
        db.session.commit()
        return {'status':status,'http_status':code},200 if ok else 502
    except Exception as e:
        db.session.add(Run(workflow_id=w.id,status='error',message=type(e).__name__+': '+str(e)[:160]));db.session.commit()
        return {'status':'error','message':str(e)[:160]},400
@app.post('/hook/<token>')
def hook(token):
    w=Workflow.query.filter_by(trigger_token=token).first_or_404()
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return {'error':'Очікується JSON object'},400
    return run_workflow(w,payload)
@app.post('/workflows/<int:wid>/test')
@login_required
def test(wid):
    w=db.get_or_404(Workflow,wid)
    try:payload=json.loads(request.form.get('sample','{}'));assert isinstance(payload,dict)
    except (ValueError,AssertionError):flash('Введи коректний JSON object','error');return redirect(url_for('workflow_detail',wid=wid))
    result,code=run_workflow(w,payload);flash(f'Тест: {result}', 'success' if code==200 else 'error');return redirect(url_for('workflow_detail',wid=wid))
@app.route('/runs')
@login_required
def runs():return render_template('runs.html',items=Run.query.order_by(Run.id.desc()).limit(150).all())
@app.route('/settings')
@login_required
def settings():return render_template('settings.html',db_type='PostgreSQL' if rawdb.startswith('postgresql') else 'SQLite')

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
