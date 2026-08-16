#!/usr/bin/env bash
# 心镜平台备份脚本（文档 11.3 数据丢失应对）
# 策略：每日凌晨本地备份保留 30 天；每周手动备份到移动硬盘；每月加密上传云端。
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_ROOT="${BACKUP_ROOT:-$APP_DIR/backups}"
DB_FILE="${DB_FILE:-$APP_DIR/backend/mind_mirror.db}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$BACKUP_ROOT/daily/$STAMP"

mkdir -p "$DEST"

echo "[backup] 备份数据库到 $DEST ..."

# SQLite 安全备份：使用 .backup 命令而非直接复制文件
sqlite3 "$DB_FILE" ".backup '$DEST/mind_mirror.db'"

# 附上配置与文档（不含密钥）
cp -r "$APP_DIR/docs" "$DEST/docs" 2>/dev/null || true

# 压缩
tar -czf "$DEST.tar.gz" -C "$BACKUP_ROOT/daily" "$STAMP"
rm -rf "$DEST"

# 保留最近 30 天
find "$BACKUP_ROOT/daily" -name "*.tar.gz" -mtime +30 -delete

# 每周（周一）复制到外部备份目录
if [ "$(date +%u)" = "1" ]; then
  WEEKLY="$BACKUP_ROOT/weekly/$STAMP.tar.gz"
  mkdir -p "$(dirname "$WEEKLY")"
  cp "$DEST.tar.gz" "$WEEKLY"
  echo "[backup] 周备份：$WEEKLY"
fi

echo "[backup] 完成：$DEST.tar.gz"
