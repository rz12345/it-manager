import re
from datetime import datetime

from croniter import croniter
from flask_wtf import FlaskForm
from wtforms import (DateTimeLocalField, RadioField, SelectField,
                     SelectMultipleField, StringField, SubmitField, TextAreaField)
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError



def validate_recipients(form, field):
    emails = [e.strip() for e in field.data.split(',') if e.strip()]
    if not emails:
        raise ValidationError('至少需要一個收件人')
    for e in emails:
        try:
            Email()(form, type('F', (), {'data': e})())
        except ValidationError:
            raise ValidationError(f'"{e}" 不是有效的 Email 格式')


_TIME_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


class TaskForm(FlaskForm):
    name = StringField('任務名稱', validators=[DataRequired(), Length(1, 100)])
    tags = StringField('標籤（逗號分隔）', validators=[Optional(), Length(max=200)])
    description = TextAreaField('備註說明', validators=[Optional()])
    group_id = SelectField('分組（可讓同組成員檢視）', coerce=int, validators=[Optional()])
    template_ids = SelectMultipleField('郵件模板', coerce=int)
    recipients = StringField('收件人（逗號分隔）',
                             validators=[DataRequired(), validate_recipients])
    schedule_mode = RadioField(
        '排程模式',
        choices=[('basic', '基本排程'), ('advanced', '進階排程 (Cron)'), ('once', '一次性')],
        default='advanced',
        validators=[DataRequired()],
    )
    # --- Basic schedule fields ---
    basic_frequency = RadioField(
        '頻率',
        choices=[('daily', '每天'), ('weekly', '每週'), ('monthly', '每月')],
        default='daily',
    )
    basic_time = StringField('時間 (HH:MM)', validators=[Optional()])
    basic_day = SelectField(
        '星期',
        coerce=int,
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
    # --- Advanced schedule fields ---
    cron_expr = StringField('Cron 表達式', validators=[Optional()])
    # --- One-time schedule field ---
    scheduled_at = DateTimeLocalField('發送時間', format='%Y-%m-%dT%H:%M',
                                      validators=[Optional()])
    submit = SubmitField('儲存')

    def validate_template_ids(self, field):
        if not field.data:
            raise ValidationError('至少選擇一個郵件模板')

    def validate_basic_time(self, field):
        if self.schedule_mode.data == 'basic':
            if not field.data or not _TIME_RE.match(field.data.strip()):
                raise ValidationError('請填寫有效時間，格式為 HH:MM（例：08:30）')

    def validate_cron_expr(self, field):
        if self.schedule_mode.data == 'advanced':
            if not field.data or not field.data.strip():
                raise ValidationError('進階排程需填寫 Cron 表達式')
            if not croniter.is_valid(field.data.strip()):
                raise ValidationError('Cron 表達式格式不正確')

    def validate_scheduled_at(self, field):
        if self.schedule_mode.data == 'once':
            if not field.data:
                raise ValidationError('一次性排程需指定發送時間')
            if field.data <= datetime.now():
                raise ValidationError('發送時間必須大於當前時間')

