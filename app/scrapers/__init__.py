from flask import Blueprint

bp = Blueprint('scrapers', __name__, url_prefix='/scrapers')

from app.scrapers import routes  # noqa: E402, F401
