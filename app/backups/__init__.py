from flask import Blueprint

bp = Blueprint('backups', __name__)

from app.backups import routes  # noqa: E402, F401
from app.backups import cli     # noqa: E402, F401
