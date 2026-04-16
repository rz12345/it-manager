"""IT-Manager 統一資料模型

兩專案合併後的核心抽象：
- Task (基底)：type='backup' | 'email'，共用排程欄位
- TaskRun (基底)：對應 type 執行一次，email 無子表、backup 有 BackupRecord
- TaskAlert (原 BackupAlert 泛化)：未讀告警 badge 來源
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db, login_manager


# ── 網路設備廠商常數 ──
DEVICE_VENDORS = ('cisco_ios', 'aruba_os', 'paloalto_panos', 'zyxel_os')

VENDOR_LABEL = {
    'cisco_ios':      'Cisco IOS Switch',
    'aruba_os':       'Aruba OS Switch',
    'paloalto_panos': 'Palo Alto PAN-OS Firewall',
    'zyxel_os':       'Zyxel Switch',
}

VENDOR_DEFAULT_COMMAND = {
    'cisco_ios':      'show running-config',
    'aruba_os':       'show running-config',
    'paloalto_panos': 'show config running',
    'zyxel_os':       'show running-config',
}


# ── 標籤顏色調色盤 ──
_TAG_COLORS = ['gray', 'brown', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink', 'red']


def _tag_color(name: str) -> str:
    return _TAG_COLORS[hash(name) % len(_TAG_COLORS)]


# ── 多對多關聯表 ──
user_groups = db.Table(
    'user_groups',
    db.Column('user_id',  db.Integer, db.ForeignKey('users.id'),  primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id'), primary_key=True),
)

task_tags = db.Table(
    'task_tags',
    db.Column('task_id', db.Integer, db.ForeignKey('tasks.id'), primary_key=True),
    db.Column('tag_id',  db.Integer, db.ForeignKey('tags.id'),  primary_key=True),
)

template_tags = db.Table(
    'template_tags',
    db.Column('template_id', db.Integer, db.ForeignKey('email_templates.id'), primary_key=True),
    db.Column('tag_id',      db.Integer, db.ForeignKey('tags.id'),            primary_key=True),
)

scraper_tags = db.Table(
    'scraper_tags',
    db.Column('scraper_id', db.Integer, db.ForeignKey('scrapers.id'), primary_key=True),
    db.Column('tag_id',     db.Integer, db.ForeignKey('tags.id'),     primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    password_changed_at = db.Column(db.DateTime, nullable=True)

    groups = db.relationship('Group', secondary=user_groups, lazy='subquery',
                             backref=db.backref('users', lazy='dynamic'))
    tasks = db.relationship('Task', backref='owner', lazy='dynamic', foreign_keys='Task.owner_id')
    email_templates = db.relationship('EmailTemplate', backref='owner', lazy='dynamic')
    scrapers = db.relationship('Scraper', backref='owner', lazy='dynamic', foreign_keys='Scraper.owner_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = datetime.now(timezone.utc)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def group_ids(self) -> list[int]:
        return [g.id for g in self.groups]

    def __repr__(self):
        return f'<User {self.username}>'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Group(db.Model):
    """細粒度權限分組：Host / Device / Task 依 group_id 歸屬，User ↔ Group 多對多授權。"""
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    hosts = db.relationship('Host', backref='group', lazy='dynamic')
    devices = db.relationship('Device', backref='group', lazy='dynamic')
    tasks = db.relationship('Task', backref='group', lazy='dynamic')
    email_templates = db.relationship('EmailTemplate', backref='group', lazy='dynamic')
    scrapers = db.relationship('Scraper', backref='group', lazy='dynamic')

    def __repr__(self):
        return f'<Group {self.name}>'


# ── 驗證庫（SSH / 設備共用帳密）──
class Credential(db.Model):
    """集中管理可復用的 SSH / 設備登入帳密；僅 Admin 可 CRUD。"""
    __tablename__ = 'credentials'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    username = db.Column(db.String(64), nullable=False)
    password_enc = db.Column(db.Text, nullable=False, default='')
    enable_password_enc = db.Column(db.Text, nullable=False, default='')
    description = db.Column(db.String(255), default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    hosts = db.relationship('Host', backref='credential', lazy='dynamic')
    devices = db.relationship('Device', backref='credential', lazy='dynamic')

    @property
    def usage_count(self) -> int:
        return self.hosts.count() + self.devices.count()

    def __repr__(self):
        return f'<Credential {self.name}>'


# ── 主機類型模板 ──
class HostTemplate(db.Model):
    __tablename__ = 'host_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    template_paths = db.relationship('HostTemplatePath', backref='template',
                                     cascade='all, delete-orphan',
                                     order_by='HostTemplatePath.id')

    def __repr__(self):
        return f'<HostTemplate {self.name}>'


class HostTemplatePath(db.Model):
    __tablename__ = 'host_template_paths'

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('host_templates.id'), nullable=False)
    path = db.Column(db.String(512), nullable=False)
    mode = db.Column(db.String(10), nullable=False, default='sftp')


# ── Linux 主機 ──
class Host(db.Model):
    __tablename__ = 'hosts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=22)
    credential_id = db.Column(db.Integer, db.ForeignKey('credentials.id'),
                              nullable=False, index=True)
    description = db.Column(db.String(256))

    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True, index=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    file_paths = db.relationship('HostFilePath', backref='host',
                                 cascade='all, delete-orphan',
                                 order_by='HostFilePath.id')
    task_runs = db.relationship('TaskRun', backref='host', lazy='dynamic',
                                foreign_keys='TaskRun.host_id',
                                cascade='all, delete-orphan')

    @property
    def last_run_info(self):
        return (self.task_runs.filter(TaskRun.type == 'backup')
                .order_by(TaskRun.started_at.desc()).first())

    def __repr__(self):
        return f'<Host {self.name} {self.ip_address}>'


class HostFilePath(db.Model):
    __tablename__ = 'host_file_paths'

    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(db.Integer, db.ForeignKey('hosts.id'), nullable=False)
    path = db.Column(db.String(512), nullable=False)
    mode = db.Column(db.String(10), nullable=False, default='sftp')
    source = db.Column(db.String(20), default='manual')


# ── 網路設備 ──
class Device(db.Model):
    __tablename__ = 'devices'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=22)
    vendor = db.Column(db.String(30), nullable=False)
    credential_id = db.Column(db.Integer, db.ForeignKey('credentials.id'),
                              nullable=False, index=True)
    backup_command = db.Column(db.String(256))
    description = db.Column(db.String(256))

    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True, index=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    task_runs = db.relationship('TaskRun', backref='device', lazy='dynamic',
                                foreign_keys='TaskRun.device_id',
                                cascade='all, delete-orphan')

    @property
    def last_run_info(self):
        return (self.task_runs.filter(TaskRun.type == 'backup')
                .order_by(TaskRun.started_at.desc()).first())

    @property
    def effective_command(self) -> str:
        return self.backup_command or VENDOR_DEFAULT_COMMAND.get(self.vendor, '')

    @property
    def vendor_label(self) -> str:
        return VENDOR_LABEL.get(self.vendor, self.vendor)

    def __repr__(self):
        return f'<Device {self.name} {self.vendor}>'


# ── 統一任務（single-table inheritance） ──
class Task(db.Model):
    """統一任務基底。

    使用 SQLAlchemy single-table inheritance，子類 `BackupTask` / `EmailTask`
    透過 `type` 欄位自動過濾，舊程式 `BackupTask.query` 語義不變。
    """
    __tablename__ = 'tasks'
    __mapper_args__ = {'polymorphic_on': 'type', 'polymorphic_identity': 'task'}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(10), nullable=False, index=True)  # 'backup' | 'email'
    description = db.Column(db.Text)

    # 排程
    schedule_mode = db.Column(db.String(10), nullable=False, default='advanced')
    # 'basic' | 'advanced' | 'once'
    schedule_basic_params = db.Column(db.JSON)
    cron_expr = db.Column(db.String(50))
    scheduled_at = db.Column(db.DateTime)

    next_run = db.Column(db.DateTime, index=True)
    last_run = db.Column(db.DateTime)
    last_status = db.Column(db.String(10))  # 'success' | 'partial' | 'failed' | 'running'
    last_message = db.Column(db.String(500))

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # 權限／擁有者
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    # backup-specific
    retain_count = db.Column(db.Integer, nullable=False, default=10)

    # email-specific
    recipients = db.Column(db.Text)          # comma-separated
    template_vars = db.Column(db.JSON, default=dict)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # backup 關聯
    targets = db.relationship('TaskTarget', backref='task',
                              cascade='all, delete-orphan',
                              order_by='TaskTarget.id')

    # email 關聯
    task_templates = db.relationship('TaskTemplate', backref='task',
                                     order_by='TaskTemplate.order',
                                     cascade='all, delete-orphan')

    # 執行紀錄
    runs = db.relationship('TaskRun', backref='task', lazy='dynamic',
                           foreign_keys='TaskRun.task_id')

    tags = db.relationship('Tag', secondary=task_tags, lazy='subquery')

    @property
    def host_ids(self) -> list[int]:
        return [t.host_id for t in self.targets if t.target_type == 'host']

    @property
    def device_ids(self) -> list[int]:
        return [t.device_id for t in self.targets if t.target_type == 'device']

    @property
    def templates(self):
        return [tt.template for tt in self.task_templates]

    def __repr__(self):
        return f'<Task {self.type}:{self.name}>'


class BackupTask(Task):
    """備份型任務（polymorphic_identity='backup'）。`BackupTask.query` 自動過濾。"""
    __mapper_args__ = {'polymorphic_identity': 'backup'}


class EmailTask(Task):
    """郵件型任務（polymorphic_identity='email'）。`EmailTask.query` 自動過濾。"""
    __mapper_args__ = {'polymorphic_identity': 'email'}


class TaskTarget(db.Model):
    """備份任務 ↔ Host/Device 關聯（host_id 與 device_id 互斥）。"""
    __tablename__ = 'task_targets'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False, index=True)
    target_type = db.Column(db.String(10), nullable=False)  # 'host' | 'device'
    host_id = db.Column(db.Integer, db.ForeignKey('hosts.id'), nullable=True, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True, index=True)

    host = db.relationship('Host', foreign_keys=[host_id])
    device = db.relationship('Device', foreign_keys=[device_id])

    __table_args__ = (
        db.UniqueConstraint('task_id', 'host_id', name='uq_task_host'),
        db.UniqueConstraint('task_id', 'device_id', name='uq_task_device'),
    )

    @property
    def target(self):
        return self.host if self.target_type == 'host' else self.device

    @property
    def target_name(self) -> str:
        t = self.target
        return t.name if t else '(deleted)'


BackupTaskTarget = TaskTarget  # 相容別名


class TaskTemplate(db.Model):
    """Email 任務的模板順序關聯。"""
    __tablename__ = 'task_templates'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('email_templates.id'), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)

    template = db.relationship('EmailTemplate')


# ── 執行紀錄（泛化） ──
class TaskRun(db.Model):
    """任一次任務執行（手動或排程）。

    backup: 可能產生多筆 BackupRecord（多檔案），host_id 或 device_id 擇一填入
    email : 一行紀錄即一次送信，recipients 存送出當下的收件清單
    """
    __tablename__ = 'task_runs'
    __mapper_args__ = {'polymorphic_on': 'type', 'polymorphic_identity': 'task_run'}

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=True, index=True)
    type = db.Column(db.String(10), nullable=False, index=True)  # 'backup' | 'email'

    # backup-specific
    target_type = db.Column(db.String(10), index=True)   # 'host' | 'device'
    host_id = db.Column(db.Integer, db.ForeignKey('hosts.id'), nullable=True, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True, index=True)
    file_count = db.Column(db.Integer, nullable=False, default=0)

    # email-specific
    recipients = db.Column(db.Text)

    status = db.Column(db.String(10), nullable=False, default='running', index=True)
    # 'running' | 'success' | 'partial' | 'failed'
    error_message = db.Column(db.Text)
    triggered_by = db.Column(db.String(10), nullable=False, default='schedule')
    # 'schedule' | 'manual' | 'api'

    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)
    finished_at = db.Column(db.DateTime)

    records = db.relationship('BackupRecord', backref='run',
                              cascade='all, delete-orphan',
                              order_by='BackupRecord.file_path')
    alerts = db.relationship('TaskAlert', backref='run',
                             cascade='all, delete-orphan')

    @property
    def target_name(self) -> str:
        if self.type == 'email':
            return (self.task.name if self.task else '(deleted)')
        if self.target_type == 'host' and self.host:
            return self.host.name
        if self.target_type == 'device' and self.device:
            return self.device.name
        return '(deleted)'

    def __repr__(self):
        return f'<TaskRun {self.type} task={self.task_id} {self.status}>'


class BackupRun(TaskRun):
    """備份執行紀錄；`BackupRun.query` 自動過濾 type='backup'。"""
    __mapper_args__ = {'polymorphic_identity': 'backup'}


class EmailRun(TaskRun):
    """寄送執行紀錄；`EmailRun.query` 自動過濾 type='email'。"""
    __mapper_args__ = {'polymorphic_identity': 'email'}


class BackupRecord(db.Model):
    """BackupRun 中的單一檔案/設定快照（僅 backup 型任務）。"""
    __tablename__ = 'backup_records'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('task_runs.id'), nullable=False, index=True)
    file_path = db.Column(db.String(512), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False)
    file_size = db.Column(db.Integer, nullable=False, default=0)
    checksum = db.Column(db.String(64))
    status = db.Column(db.String(10), nullable=False, default='success')
    error_message = db.Column(db.Text)


# ── 告警（泛化） ──
class TaskAlert(db.Model):
    """未讀告警，Dashboard 顯示 badge；指向失敗/部分失敗的 TaskRun（backup 或 email）。"""
    __tablename__ = 'task_alerts'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('task_runs.id'), nullable=False, index=True)
    severity = db.Column(db.String(10), nullable=False, default='error')
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)


# 相容別名：`BackupAlert` 僅有一處使用（badge），直接等同 `TaskAlert`
BackupAlert = TaskAlert
# 相容別名：`BackupTaskTarget` == `TaskTarget`（非繼承類別，直接 alias）


# ── 郵件模板 ──
class EmailTemplate(db.Model):
    __tablename__ = 'email_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body_path = db.Column(db.String(256), nullable=False)
    variables = db.Column(db.JSON, default=list)
    scraper_vars = db.Column(db.JSON, default=dict)  # {var_name: scraper_id}
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    attachments = db.relationship('Attachment', backref='template',
                                  order_by='Attachment.uploaded_at',
                                  cascade='all, delete-orphan')
    tags = db.relationship('Tag', secondary=template_tags, lazy='subquery')


class Attachment(db.Model):
    __tablename__ = 'attachments'

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('email_templates.id'), nullable=False)
    filename = db.Column(db.String(256), nullable=False)
    storage_path = db.Column(db.String(256), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


# ── 爬蟲資料來源 ──
class Scraper(db.Model):
    __tablename__ = 'scrapers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(2048), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True, index=True)
    extract_type = db.Column(db.String(10), nullable=False)  # 'css' | 'regex' | 'js'
    extract_pattern = db.Column(db.Text, nullable=False)
    last_content = db.Column(db.Text)
    last_checked = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    scraper_logs = db.relationship('ScraperLog', backref='scraper', lazy='dynamic',
                                   cascade='all, delete-orphan')
    tags = db.relationship('Tag', secondary=scraper_tags, lazy='subquery')


class ScraperLog(db.Model):
    __tablename__ = 'scraper_logs'

    id = db.Column(db.Integer, primary_key=True)
    scraper_id = db.Column(db.Integer, db.ForeignKey('scrapers.id'), nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)  # 'success' | 'error'
    content = db.Column(db.Text)
    error_message = db.Column(db.Text)
    checked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)


# ── 個人分類標籤（email 側） ──
class Tag(db.Model):
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(20), nullable=False, default='secondary')
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (db.UniqueConstraint('name', 'owner_id', name='uq_tag_name_owner'),)


# ── 系統活動紀錄 ──
class LoginLog(db.Model):
    __tablename__ = 'login_logs'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username   = db.Column(db.String(50), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    action     = db.Column(db.String(20), nullable=False, default='login')
    status     = db.Column(db.String(10), nullable=False)
    logged_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)


# ── 設定 KV ──
class AppSetting(db.Model):
    __tablename__ = 'app_settings'

    key   = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False, default='')


