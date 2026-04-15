import json

from flask_wtf import FlaskForm
from wtforms import HiddenField, MultipleFileField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError


from app.config import Config


class TemplateForm(FlaskForm):
    name = StringField('模板名稱', validators=[DataRequired(), Length(1, 100)])
    tags = StringField('標籤（逗號分隔）', validators=[Optional(), Length(max=200)])
    subject = StringField('郵件主旨', validators=[DataRequired(), Length(1, 200)])
    body = TextAreaField('HTML 內容', validators=[DataRequired()])
    variables = StringField('可用變數（逗號分隔，例：name,date）', validators=[Optional()])
    scraper_vars = HiddenField('Scraper Vars', default='{}')
    attachments = MultipleFileField('附件', validators=[Optional()])
    submit = SubmitField('儲存')

    def validate_scraper_vars(self, field):
        if field.data:
            try:
                data = json.loads(field.data)
                if not isinstance(data, dict):
                    raise ValidationError('scraper_vars 格式錯誤')
            except (json.JSONDecodeError, TypeError):
                raise ValidationError('scraper_vars 格式錯誤')

    def validate_attachments(self, field):
        allowed = Config.ALLOWED_EXTENSIONS
        for f in field.data:
            if not f.filename:
                continue
            ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
            if ext not in allowed:
                raise ValidationError(f'不允許的檔案格式：{f.filename}')
