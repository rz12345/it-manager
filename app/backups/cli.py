import os
import shutil

import click
from flask import current_app

from app import db
from app.backups import bp
from app.models import BackupRecord, BackupRun


def _purge_all(yes):
    """模式 all：刪除所有 Run / Record / Alert 與 backups/ 下實體檔案。"""
    run_count = BackupRun.query.count()

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

    click.echo('將刪除：')
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


def _prune_orphans(yes, dry_run):
    """模式 orphans：清除實體檔案已遺失的 BackupRecord 孤兒列。
    若整個 BackupRun 的所有 record 都成為孤兒，則連 Run 一併刪除。
    """
    orphans = []
    for rec in BackupRecord.query.all():
        if not rec.storage_path or not os.path.exists(rec.storage_path):
            orphans.append(rec)

    if not orphans:
        click.echo('沒有孤兒 BackupRecord。')
        return

    click.echo(f'找到 {len(orphans)} 筆孤兒 BackupRecord：')
    for rec in orphans[:20]:
        click.echo(f'  - record#{rec.id} run#{rec.run_id} {rec.file_path}')
    if len(orphans) > 20:
        click.echo(f'  ...（另有 {len(orphans) - 20} 筆）')

    if dry_run:
        click.echo('（dry-run，未刪除任何資料）')
        return

    if not yes and not click.confirm('確定刪除上述孤兒列？'):
        click.echo('已取消。')
        return

    run_ids = {rec.run_id for rec in orphans}
    for rec in orphans:
        db.session.delete(rec)
    db.session.flush()

    empty_runs = (BackupRun.query
                  .filter(BackupRun.id.in_(run_ids))
                  .filter(~BackupRun.records.any())
                  .all())
    for run in empty_runs:
        db.session.delete(run)

    db.session.commit()
    click.echo(f'✓ 已刪除 {len(orphans)} 筆 BackupRecord、{len(empty_runs)} 筆空的 BackupRun。')


@bp.cli.command('clean')
@click.option('--mode', type=click.Choice(['orphans', 'all']), required=True,
              help='orphans：僅清除實體檔案遺失的 DB 孤兒列；all：清除所有備份紀錄與檔案')
@click.option('--yes', is_flag=True, help='略過互動確認')
@click.option('--dry-run', is_flag=True, help='僅列出（僅 --mode=orphans 支援）')
def clean(mode, yes, dry_run):
    """清理備份資料。依 --mode 決定清除範圍。"""
    if mode == 'all':
        if dry_run:
            raise click.UsageError('--dry-run 僅支援於 --mode=orphans')
        _purge_all(yes)
    else:
        _prune_orphans(yes, dry_run)
