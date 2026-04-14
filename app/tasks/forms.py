import re
from datetime import datetime

from flask_wtf import FlaskForm
from wtforms import (BooleanField, DateTimeLocalField, IntegerField,
                     RadioField, SelectField, SelectMultipleField,
                     StringField, SubmitField, TextAreaField)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError


_TIME_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


class BackupTaskForm(FlaskForm):
    name = StringField('任務名稱', validators=[DataRequired(), Length(1, 100)])
    description = TextAreaField('備註說明', validators=[Optional()])

    host_ids = SelectMultipleField('Linux 主機', coerce=int)
    device_ids = SelectMultipleField('網路設備', coerce=int)

    schedule_mode = RadioField(
        '排程模式',
        choices=[('basic', '基本排程'), ('advanced', '進階排程 (Cron)'), ('once', '一次性')],
        default='advanced',
        validators=[DataRequired()],
    )
    basic_frequency = RadioField(
        '頻率',
        choices=[('daily', '每天'), ('weekly', '每週'), ('monthly', '每月')],
        default='daily',
    )
    basic_time = StringField('時間 (HH:MM)', validators=[Optional()])
    basic_day = SelectField(
        '星期', coerce=int,
        choices=[(1, '週一'), (2, '週二'), (3, '週三'),
                 (4, '週四'), (5, '週五'), (6, '週六'), (0, '週日')],
        default=1,
    )
    basic_week = SelectField(
        '第幾週',
        choices=[('1', '第 1 週'), ('2', '第 2 週'), ('3', '第 3 週'),
                 ('4', '第 4 週'), ('L', '最後一週')],
        default='1',
    )
    cron_expr = StringField('Cron 表達式', validators=[Optional(), Length(max=50)])
    scheduled_at = DateTimeLocalField('執行時間', format='%Y-%m-%dT%H:%M',
                                      validators=[Optional()])

    retain_count = IntegerField(
        '保留版本數', default=10,
        validators=[DataRequired(), NumberRange(min=1, max=1000)],
        description='每個目標保留最近 N 次執行結果，超過則自動清除',
    )

    is_active = BooleanField('啟用此任務', default=True)
    submit = SubmitField('儲存')

    def validate(self, *args, **kwargs):
        if not super().validate(*args, **kwargs):
            return False
        if not (self.host_ids.data or self.device_ids.data):
            self.host_ids.errors.append('至少需選擇一台主機或設備')
            return False
        return True

    def validate_basic_time(self, field):
        if self.schedule_mode.data == 'basic':
            if not field.data or not _TIME_RE.match(field.data.strip()):
                raise ValidationError('請填寫有效時間，格式 HH:MM（例：08:30）')

    def validate_cron_expr(self, field):
        if self.schedule_mode.data == 'advanced':
            if not field.data or not field.data.strip():
                raise ValidationError('進階排程需填寫 Cron 表達式')
            try:
                from croniter import croniter
                if not croniter.is_valid(field.data.strip()):
                    raise ValidationError('Cron 表達式格式不正確')
            except ImportError:
                pass

    def validate_scheduled_at(self, field):
        if self.schedule_mode.data == 'once':
            if not field.data:
                raise ValidationError('一次性排程需指定執行時間')
            if field.data <= datetime.now():
                raise ValidationError('執行時間必須大於當前時間')
