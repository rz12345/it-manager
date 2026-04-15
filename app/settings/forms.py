from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, NumberRange, Optional, Length


class NotifyForm(FlaskForm):
    SMTP_HOST = StringField('SMTP Host', validators=[Optional(), Length(max=128)])
    SMTP_PORT = IntegerField('SMTP Port', validators=[Optional(), NumberRange(1, 65535)])
    SMTP_USER = StringField('SMTP 帳號', validators=[Optional(), Length(max=128)])
    SMTP_PASS = PasswordField('SMTP 密碼（留白保留原值）', validators=[Optional(), Length(max=128)])
    SMTP_FROM = StringField('寄件者 Email', validators=[Optional(), Email(), Length(max=128)])
    NOTIFY_EMAIL = StringField('告警收件者 Email', validators=[Optional(), Email(), Length(max=128)])
    TEST_EMAIL   = StringField('測試收件者 Email（Email 任務 test-send 使用）',
                               validators=[Optional(), Email(), Length(max=128)])
    submit = SubmitField('儲存設定')


class TimeoutForm(FlaskForm):
    SSH_TIMEOUT_SECONDS = IntegerField('SSH 逾時（秒）',
                                       validators=[Optional(), NumberRange(5, 600)])
    NETMIKO_TIMEOUT_SECONDS = IntegerField('Netmiko 逾時（秒）',
                                           validators=[Optional(), NumberRange(5, 600)])
    SCHEDULER_MAX_WORKERS   = IntegerField('排程併發數',
                                           validators=[Optional(), NumberRange(1, 50)])
    submit = SubmitField('儲存設定')


class PasswordPolicyForm(FlaskForm):
    PW_MIN_LENGTH  = IntegerField('密碼最短長度',
                                  validators=[DataRequired(), NumberRange(min=1, max=128)])
    PW_MIN_UPPER   = IntegerField('須含大寫字母數',
                                  validators=[Optional(), NumberRange(min=0, max=10)])
    PW_MIN_LOWER   = IntegerField('須含小寫字母數',
                                  validators=[Optional(), NumberRange(min=0, max=10)])
    PW_MIN_DIGIT   = IntegerField('須含數字數',
                                  validators=[Optional(), NumberRange(min=0, max=10)])
    PW_MIN_SPECIAL = IntegerField('須含特殊字元數',
                                  validators=[Optional(), NumberRange(min=0, max=10)])
    PW_EXPIRE_DAYS = IntegerField('密碼有效天數（0=不過期）',
                                  validators=[Optional(), NumberRange(min=0, max=3650)])
    submit         = SubmitField('儲存規則')


class UserCreateForm(FlaskForm):
    username = StringField('帳號', validators=[DataRequired(), Length(1, 50)])
    email    = StringField('Email', validators=[DataRequired(), Email(), Length(1, 120)])
    password = PasswordField('密碼', validators=[DataRequired()])
    is_admin = BooleanField('管理者權限')
    submit   = SubmitField('新增帳號')
