from flask import Blueprint

bp = Blueprint('assets', __name__)

from app.assets import routes  # noqa: E402,F401
