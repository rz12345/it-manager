from flask import Blueprint

bp = Blueprint('email_tasks', __name__)

from app.email_tasks import routes  # noqa: E402, F401
