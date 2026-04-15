from flask_wtf import FlaskForm
from wtforms import (BooleanField, IntegerField, SelectField,
                     StringField, SubmitField)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models import DEVICE_VENDORS, VENDOR_LABEL


class DeviceForm(FlaskForm):
    name = StringField('設備名稱', validators=[DataRequired(), Length(max=100)])
    ip_address = StringField('IP / Hostname',
                             validators=[DataRequired(), Length(max=45)])
    port = IntegerField('SSH Port', default=22,
                        validators=[DataRequired(), NumberRange(min=1, max=65535)])
    vendor = SelectField(
        '廠商',
        choices=[(v, VENDOR_LABEL[v]) for v in DEVICE_VENDORS],
        validators=[DataRequired()],
    )
    credential_id = SelectField(
        '登入驗證',
        coerce=int,
        choices=[],
        validators=[DataRequired(message='請選擇一組驗證')],
        description='於「設定 → 驗證庫」維護可共用的帳密（含 enable 密碼）',
    )
    backup_command = StringField(
        '備份指令',
        validators=[Optional(), Length(max=256)],
        description='留白使用廠商預設指令',
    )
    description = StringField('備註', validators=[Optional(), Length(max=256)])

    group_id = SelectField('分組', coerce=int, choices=[], validators=[Optional()])

    is_active = BooleanField('啟用此設備', default=True)
    submit = SubmitField('儲存')
