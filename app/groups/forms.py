from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectMultipleField, widgets
from wtforms.validators import DataRequired, Length, Optional


class _MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class GroupForm(FlaskForm):
    name = StringField(
        '分組名稱',
        validators=[DataRequired(), Length(max=100)],
    )
    description = StringField(
        '描述',
        validators=[Optional(), Length(max=256)],
    )
    members = _MultiCheckboxField(
        '成員',
        coerce=int,
        choices=[],
    )
    submit = SubmitField('儲存')
