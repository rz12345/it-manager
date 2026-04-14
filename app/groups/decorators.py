from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def admin_required(f):
    """Require authenticated admin user."""
    @wraps(f)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def user_can_access(obj) -> bool:
    """權限檢查：Admin 全通；一般使用者需隸屬於目標 Host/Device 所屬 Group。

    - obj: Host 或 Device 實例（需有 group_id 屬性）
    - obj.group_id 為 None 時僅 Admin 可存取
    """
    if not current_user.is_authenticated:
        return False
    if current_user.is_admin:
        return True
    if obj is None or obj.group_id is None:
        return False
    return obj.group_id in current_user.group_ids


def require_group_access(loader):
    """Decorator：由 loader(**kwargs) 取得 Host/Device，檢查 current_user 是否有權存取。

    用法:
        @bp.route('/hosts/<int:host_id>')
        @require_group_access(lambda host_id: Host.query.get_or_404(host_id))
        def detail(host_id):
            ...

    被包裝函式會收到 loader 載入的物件作為第一參數 `obj`。
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            obj = loader(**kwargs)
            if not user_can_access(obj):
                abort(403)
            return f(obj, *args, **kwargs)
        return wrapped
    return decorator
