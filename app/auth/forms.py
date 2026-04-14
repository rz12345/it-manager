from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class LoginForm(FlaskForm):
    username = StringField('使用者名稱', validators=[DataRequired(), Length(max=50)])
    password = PasswordField('密碼', validators=[DataRequired()])
    remember = BooleanField('記住我')
    submit = SubmitField('登入')


class SetupForm(FlaskForm):
    """首次啟動建立 Admin 帳號。"""
    username = StringField('管理者帳號', validators=[DataRequired(), Length(min=3, max=50)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField(
        '密碼',
        validators=[DataRequired(), Length(min=8, message='密碼至少 8 碼')],
    )
    password_confirm = PasswordField(
        '再次輸入密碼',
        validators=[DataRequired(), EqualTo('password', message='兩次密碼需相同')],
    )
    submit = SubmitField('建立管理者')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('目前密碼', validators=[DataRequired()])
    new_password = PasswordField('新密碼', validators=[DataRequired()])
    new_password2 = PasswordField(
        '確認新密碼',
        validators=[DataRequired(), EqualTo('new_password', message='兩次輸入的密碼不一致')],
    )
    submit = SubmitField('變更密碼')
