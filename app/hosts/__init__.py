from flask import Blueprint

bp = Blueprint('hosts', __name__, cli_group='hosts')

from app.hosts import routes  # noqa: E402, F401
from app.hosts import cli     # noqa: E402, F401
