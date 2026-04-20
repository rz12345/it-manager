from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange


class MacTraceForm(FlaskForm):
    mac = StringField(
        'MAC Address',
        validators=[DataRequired(message='請輸入 MAC'), Length(max=32)],
        description='支援 aa:bb:cc:dd:ee:ff、aabb.ccdd.eeff、AA-BB-CC-DD-EE-FF、aabbccddeeff',
    )
    start_device_id = SelectField(
        '起點 switch',
        coerce=int,
        choices=[],        # 由 view 動態填入
        validators=[DataRequired(message='請選擇起點 switch')],
    )
    max_hops = IntegerField(
        '最大 hop 數',
        default=10,
        validators=[DataRequired(), NumberRange(min=1, max=20)],
    )
    submit = SubmitField('開始追蹤')
