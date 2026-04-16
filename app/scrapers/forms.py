import re

from flask_wtf import FlaskForm
from wtforms import RadioField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, URL, ValidationError


class ScraperForm(FlaskForm):
    name = StringField('爬蟲名稱', validators=[DataRequired(), Length(1, 100)])
    tags = StringField('標籤（逗號分隔）', validators=[Optional(), Length(max=200)])
    group_id = SelectField('分組（可讓同組成員檢視）', coerce=int, validators=[Optional()])
    url = StringField('目標 URL', validators=[DataRequired(), URL(), Length(max=2048)])
    extract_type = RadioField(
        '擷取方式',
        choices=[('css', 'CSS 選擇器'), ('regex', '正規表達式'), ('js', 'JavaScript (Playwright)')],
        default='css',
        validators=[DataRequired()],
    )
    extract_pattern = TextAreaField('擷取規則', validators=[DataRequired(), Length(max=4096)])
    submit = SubmitField('儲存')

    def validate_extract_pattern(self, field):
        if self.extract_type.data == 'regex':
            try:
                re.compile(field.data)
            except re.error as exc:
                raise ValidationError(f'正規表達式格式錯誤: {exc}')
        elif self.extract_type.data == 'js':
            snippet = field.data.strip()
            if not (snippet.startswith('()') or snippet.startswith('() ')):
                raise ValidationError('JavaScript 擷取規則必須是函式表達式，例如：() => { ... }')
