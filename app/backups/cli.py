import os
import shutil

import click

from app import db
from app.backups import bp
from app.models import BackupRun


@bp.cli.command('purge-all')
@click.option('--yes', is_flag=True, help='略過互動確認')
def purge_all(yes):
    """清除所有備份紀錄（BackupRun / BackupRecord / BackupAlert）與 backups/ 檔案。
    保留 BackupTask、Host、Device、使用者與分組設定。
    """
    run_count = BackupRun.query.count()

    from flask import current_app
    project_root = os.path.dirname(current_app.root_path)
    backup_dirs = [
        os.path.join(project_root, 'backups', 'hosts'),
        os.path.join(project_root, 'backups', 'devices'),
    ]

    file_count = 0
    dir_count = 0
    for root_dir in backup_dirs:
        if not os.path.isdir(root_dir):
            continue
        for entry in os.listdir(root_dir):
            full = os.path.join(root_dir, entry)
            if os.path.isdir(full):
                dir_count += 1
                for r, _, files in os.walk(full):
                    file_count += len(files)
            elif os.path.isfile(full):
                file_count += 1

    click.echo(f'將刪除：')
    click.echo(f'  BackupRun: {run_count} 筆（連同 BackupRecord / BackupAlert cascade 刪除）')
    click.echo(f'  備份檔案: {file_count} 個（分散在 {dir_count} 個子目錄）')
    click.echo(f'  備份根目錄: {backup_dirs}')

    if run_count == 0 and file_count == 0:
        click.echo('沒有資料需要清除。')
        return

    if not yes and not click.confirm('確定要全部清除？此操作不可逆。'):
        click.echo('已取消。')
        return

    BackupRun.query.delete(synchronize_session=False)
    db.session.commit()
    click.echo(f'✓ 已刪除 {run_count} 筆 BackupRun（含 records / alerts）')

    removed_files = 0
    for root_dir in backup_dirs:
        if not os.path.isdir(root_dir):
            continue
        for entry in os.listdir(root_dir):
            full = os.path.join(root_dir, entry)
            try:
                if os.path.isdir(full):
                    for r, _, files in os.walk(full):
                        removed_files += len(files)
                    shutil.rmtree(full)
                elif os.path.isfile(full):
                    os.remove(full)
                    removed_files += 1
            except OSError as e:
                click.echo(f'  警告：無法刪除 {full}：{e}', err=True)
    click.echo(f'✓ 已刪除 {removed_files} 個備份檔案')
    click.echo('完成。')
