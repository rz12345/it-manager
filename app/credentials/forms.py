from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class CredentialForm(FlaskForm):
    name = StringField('顯示名稱', validators=[DataRequired(), Length(max=128)],
                       description='可辨識用途，如「核心機房 root」、「Cisco SW 共用」')
    username = StringField('使用者', validators=[DataRequired(), Length(max=64)])
    password = PasswordField(
        '密碼',
        validators=[Optional(), Length(max=256)],
        description='編輯時留白則保留原密碼',
    )
    enable_password = PasswordField(
        'Enable 密碼',
        validators=[Optional(), Length(max=256)],
        description='網路設備 privileged 模式用（選填，編輯時留白保留原值）',
    )
    description = StringField('備註', validators=[Optional(), Length(max=255)])
    submit = SubmitField('儲存')
