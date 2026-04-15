from flask import Blueprint

bp = Blueprint('credentials', __name__)

from app.credentials import routes  # noqa: E402, F401
