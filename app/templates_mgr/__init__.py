from flask import Blueprint

bp = Blueprint('templates_mgr', __name__, url_prefix='/templates')

from app.templates_mgr import routes  # noqa: E402, F401
