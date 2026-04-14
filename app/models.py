from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db, login_manager

# ── 網路設備廠商常數 ──
DEVICE_VENDORS = ('cisco_ios', 'aruba_os', 'paloalto_panos')

VENDOR_LABEL = {
    'cisco_ios':      'Cisco IOS Switch',
    'aruba_os':       'Aruba OS Switch',
    'paloalto_panos': 'Palo Alto PAN-OS Firewall',
}

VENDOR_DEFAULT_COMMAND = {
    'cisco_ios':      'show running-config',
    'aruba_os':       'show running-config',
    'paloalto_panos': 'show config running',
}


# ── 多對多關聯表：User ↔ Group ──
user_groups = db.Table(
    'user_groups',
    db.Column('user_id',  db.Integer, db.ForeignKey('users.id'),  primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id'), primary_key=True),
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
    """細粒度權限分組：Host / Device 依 group_id 歸屬，User ↔ Group 多對多授權。"""
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    hosts = db.relationship('Host', backref='group', lazy='dynamic')
    devices = db.relationship('Device', backref='group', lazy='dynamic')

    def __repr__(self):
        return f'<Group {self.name}>'


# ── 主機類型模板 ──
class HostTemplate(db.Model):
    """主機類型模板（Web Server / DB Server 等），可快速套用預設備份路徑。"""
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
    """主機模板中的預設備份路徑（支援 Glob）。"""
    __tablename__ = 'host_template_paths'

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('host_templates.id'), nullable=False)
    path = db.Column(db.String(512), nullable=False)

    def __repr__(self):
        return f'<HostTemplatePath {self.path}>'


# ── Linux 主機 ──
class Host(db.Model):
    __tablename__ = 'hosts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=22)
    username = db.Column(db.String(64), nullable=False)
    password_enc = db.Column(db.Text, nullable=False, default='')  # Fernet 加密
    description = db.Column(db.String(256))

    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True, index=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    file_paths = db.relationship('HostFilePath', backref='host',
                                 cascade='all, delete-orphan',
                                 order_by='HostFilePath.id')
    backup_runs = db.relationship('BackupRun', backref='host', lazy='dynamic',
                                  foreign_keys='BackupRun.host_id',
                                  cascade='all, delete-orphan')

    @property
    def last_run_info(self):
        """回傳最近一次 BackupRun（跨所有 BackupTask），無則 None。"""
        return (self.backup_runs
                .order_by(BackupRun.started_at.desc()).first())

    def __repr__(self):
        return f'<Host {self.name} {self.ip_address}>'


class HostFilePath(db.Model):
    """主機實際要備份的檔案路徑（支援 Glob，如 /etc/nginx/conf.d/*.conf）。"""
    __tablename__ = 'host_file_paths'

    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(db.Integer, db.ForeignKey('hosts.id'), nullable=False)
    path = db.Column(db.String(512), nullable=False)
    source = db.Column(db.String(20), default='manual')  # 'manual' | 'template'

    def __repr__(self):
        return f'<HostFilePath host={self.host_id} {self.path}>'


# ── 網路設備 ──
class Device(db.Model):
    __tablename__ = 'devices'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=22)
    vendor = db.Column(db.String(30), nullable=False)         # cisco_ios / aruba_os / paloalto_panos
    username = db.Column(db.String(64), nullable=False)
    password_enc = db.Column(db.Text, nullable=False, default='')  # Fernet 加密
    enable_password_enc = db.Column(db.Text, default='')           # Cisco enable 模式（選填）
    backup_command = db.Column(db.String(256))                # 留空使用廠商預設指令
    description = db.Column(db.String(256))

    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True, index=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    backup_runs = db.relationship('BackupRun', backref='device', lazy='dynamic',
                                  foreign_keys='BackupRun.device_id',
                                  cascade='all, delete-orphan')

    @property
    def effective_command(self) -> str:
        return self.backup_command or VENDOR_DEFAULT_COMMAND.get(self.vendor, '')

    @property
    def vendor_label(self) -> str:
        return VENDOR_LABEL.get(self.vendor, self.vendor)

    @property
    def last_run_info(self):
        return (self.backup_runs
                .order_by(BackupRun.started_at.desc()).first())

    def __repr__(self):
        return f'<Device {self.name} {self.vendor}>'


# ── 備份執行紀錄 ──
class BackupRun(db.Model):
    """一次備份執行（手動或排程）。
    - 主機：可能產生多筆 BackupRecord（多檔案）
    - 設備：一筆 BackupRecord（running-config）
    版本保留（retain_count）以 BackupRun 為單位。
    """
    __tablename__ = 'backup_runs'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('backup_tasks.id'), nullable=True, index=True)
    target_type = db.Column(db.String(10), nullable=False, index=True)  # 'host' | 'device'
    host_id = db.Column(db.Integer, db.ForeignKey('hosts.id'), nullable=True, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True, index=True)

    status = db.Column(db.String(10), nullable=False, default='running', index=True)
    # 'running' | 'success' | 'partial' | 'failed'
    file_count = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text)
    triggered_by = db.Column(db.String(10), nullable=False, default='schedule')
    # 'schedule' | 'manual' | 'api'

    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)
    finished_at = db.Column(db.DateTime)

    records = db.relationship('BackupRecord', backref='run',
                              cascade='all, delete-orphan',
                              order_by='BackupRecord.file_path')
    alerts = db.relationship('BackupAlert', backref='run',
                             cascade='all, delete-orphan')

    @property
    def target_name(self) -> str:
        if self.target_type == 'host' and self.host:
            return self.host.name
        if self.target_type == 'device' and self.device:
            return self.device.name
        return '(deleted)'

    def __repr__(self):
        return f'<BackupRun {self.target_type}={self.host_id or self.device_id} {self.status}>'


class BackupRecord(db.Model):
    """BackupRun 中的單一檔案/設定快照。"""
    __tablename__ = 'backup_records'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('backup_runs.id'), nullable=False, index=True)
    file_path = db.Column(db.String(512), nullable=False)
    # 主機：原始路徑（可能來自 Glob 展開後的具體路徑）
    # 設備：固定為 'running-config'
    storage_path = db.Column(db.String(512), nullable=False)  # 本地實體檔案絕對路徑
    file_size = db.Column(db.Integer, nullable=False, default=0)
    checksum = db.Column(db.String(64))                       # SHA256 hex
    status = db.Column(db.String(10), nullable=False, default='success')  # 'success' | 'failed'
    error_message = db.Column(db.Text)

    def __repr__(self):
        return f'<BackupRecord run={self.run_id} {self.file_path}>'


# ── 備份任務（多目標排程） ──
class BackupTask(db.Model):
    """備份任務：綁定多台 Host 與／或 Device，共用同一排程設定。"""
    __tablename__ = 'backup_tasks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)

    # 排程設定
    schedule_mode = db.Column(db.String(10), nullable=False, default='advanced')
    # 'basic' | 'advanced' | 'once'
    schedule_basic_params = db.Column(db.JSON)   # 僅 basic 模式使用
    cron_expr = db.Column(db.String(50))         # basic/advanced
    scheduled_at = db.Column(db.DateTime)        # once 模式（UTC naive）

    retain_count = db.Column(db.Integer, nullable=False, default=10)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    next_run = db.Column(db.DateTime, index=True)
    last_run = db.Column(db.DateTime)
    last_status = db.Column(db.String(10))       # 'success' | 'partial' | 'failed'

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    targets = db.relationship('BackupTaskTarget', backref='task',
                              cascade='all, delete-orphan',
                              order_by='BackupTaskTarget.id')
    backup_runs = db.relationship('BackupRun', backref='task', lazy='dynamic',
                                  foreign_keys='BackupRun.task_id')

    @property
    def host_ids(self) -> list[int]:
        return [t.host_id for t in self.targets if t.target_type == 'host']

    @property
    def device_ids(self) -> list[int]:
        return [t.device_id for t in self.targets if t.target_type == 'device']

    def __repr__(self):
        return f'<BackupTask {self.name}>'


class BackupTaskTarget(db.Model):
    """任務 ↔ Host/Device 關聯（host_id 與 device_id 互斥）。"""
    __tablename__ = 'backup_task_targets'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('backup_tasks.id'), nullable=False, index=True)
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


# ── 告警 ──
class BackupAlert(db.Model):
    """未讀告警，Dashboard 顯示 badge；指向失敗/部分失敗的 BackupRun。"""
    __tablename__ = 'backup_alerts'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('backup_runs.id'), nullable=False, index=True)
    severity = db.Column(db.String(10), nullable=False, default='error')  # 'error' | 'warning'
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)

    def __repr__(self):
        return f'<BackupAlert run={self.run_id} {self.severity}>'


# ── 系統活動紀錄 ──
class LoginLog(db.Model):
    __tablename__ = 'login_logs'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username   = db.Column(db.String(50), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    action     = db.Column(db.String(20), nullable=False, default='login')
    # 'login' | 'logout' | 'password_changed' | 'password_reset'
    status     = db.Column(db.String(10), nullable=False)  # 'success' / 'failed'
    logged_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)

    def __repr__(self):
        return f'<LoginLog {self.username} {self.action} {self.status}>'


# ── 設定 KV 表 ──
class AppSetting(db.Model):
    __tablename__ = 'app_settings'

    key   = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False, default='')

    def __repr__(self):
        return f'<AppSetting {self.key}>'
