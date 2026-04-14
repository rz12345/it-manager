from flask_wtf import FlaskForm
from wtforms import (BooleanField, IntegerField, PasswordField, SelectField,
                     StringField, SubmitField, TextAreaField)
from wtforms.validators import (DataRequired, IPAddress, Length, NumberRange,
                                Optional, Regexp)  # noqa: F401


class HostForm(FlaskForm):
    name = StringField('主機名稱', validators=[DataRequired(), Length(max=100)])
    ip_address = StringField(
        'IP / Hostname',
        validators=[DataRequired(), Length(max=45)],
    )
    port = IntegerField(
        'SSH Port',
        default=22,
        validators=[DataRequired(), NumberRange(min=1, max=65535)],
    )
    username = StringField('SSH 使用者', validators=[DataRequired(), Length(max=64)])
    password = PasswordField(
        'SSH 密碼',
        validators=[Optional(), Length(max=256)],
        description='編輯時留白則保留原密碼',
    )
    description = StringField('備註', validators=[Optional(), Length(max=256)])

    group_id = SelectField('分組', coerce=int, choices=[], validators=[Optional()])
    template_id = SelectField(
        '套用主機類型模板',
        coerce=int,
        choices=[],
        validators=[Optional()],
        description='僅在建立時展開模板路徑清單；之後可手動增刪',
    )

    is_active = BooleanField('啟用此主機', default=True)
    submit = SubmitField('儲存')


class HostFilePathForm(FlaskForm):
    """新增單一備份路徑（支援 Glob，如 /etc/nginx/conf.d/*.conf）。"""
    path = StringField(
        '備份路徑',
        validators=[DataRequired(), Length(max=512),
                    Regexp(r'^/', message='請使用絕對路徑（以 / 開頭）')],
    )
    submit = SubmitField('新增路徑')


class HostTemplateForm(FlaskForm):
    """主機類型模板（Web Server / DB Server 等）。"""
    name = StringField('模板名稱', validators=[DataRequired(), Length(max=100)])
    description = StringField('描述', validators=[Optional(), Length(max=256)])
    submit = SubmitField('儲存')


class HostTemplatePathForm(FlaskForm):
    """模板內預設備份路徑（支援 Glob）。"""
    path = StringField(
        '預設路徑',
        validators=[DataRequired(), Length(max=512),
                    Regexp(r'^/', message='請使用絕對路徑（以 / 開頭）')],
    )
    submit = SubmitField('新增路徑')
