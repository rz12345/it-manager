from flask import Blueprint

bp = Blueprint('logs', __name__)

from app.logs import routes  # noqa: E402, F401
