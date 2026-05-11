#!/usr/bin/env bash
# ============================================================
#  RPi5 Storage Cleanup Script
#  Frees disk space on the RPi5 by archiving/removing old data.
#
#  Usage:
#    bash cleanup_rpi_storage.sh              (interactive)
#    bash cleanup_rpi_storage.sh --dry-run    (show what would be done)
#    bash cleanup_rpi_storage.sh --auto       (non-interactive, safe defaults)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Paths
RAW_DIR="$REPO_ROOT/Daluyan_V2/backend/data/raw"
PARQUET_DIR="$REPO_ROOT/Daluyan_V2/backend/data/parquet"
DUCKDB_PATH="$REPO_ROOT/Daluyan_V2/backend/data/daluyan.duckdb"
ARTIFACTS_DIR="$REPO_ROOT/Ferry_digial_shadow/Models/artifacts"
GIT_DIR="$REPO_ROOT/.git"
LOG_FILES="$REPO_ROOT/Daluyan_V2/*.log"

# Config
RAW_CSV_MAX_AGE_DAYS=90   # Archive raw CSVs older than this
ARCHIVE_DIR="$REPO_ROOT/Daluyan_V2/backend/data/archived_raw"
DISK_WARN_PCT=80

# Modes
DRY_RUN=false
AUTO_MODE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --auto)    AUTO_MODE=true; shift ;;
        -h|--help)
            echo "Usage: bash cleanup_rpi_storage.sh [--dry-run] [--auto]"
            echo "  --dry-run  Show what would be done without making changes"
            echo "  --auto     Non-interactive mode with safe defaults"
            exit 0
            ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# ── Helpers ──

log() { echo "[$(date '+%H:%M:%S')] $*"; }

confirm() {
    if $AUTO_MODE; then return 0; fi
    if $DRY_RUN; then return 1; fi
    read -rp "$1 [y/N] " answer
    [[ "$answer" =~ ^[Yy] ]]
}

human_size() {
    local bytes=$1
    if (( bytes >= 1073741824 )); then
        echo "$(( bytes / 1073741824 )) GB"
    elif (( bytes >= 1048576 )); then
        echo "$(( bytes / 1048576 )) MB"
    elif (( bytes >= 1024 )); then
        echo "$(( bytes / 1024 )) KB"
    else
        echo "$bytes B"
    fi
}

# ── Disk Usage Report ──

echo "============================================================"
echo "  RPi5 Storage Cleanup"
if $DRY_RUN; then echo "  MODE: DRY RUN (no changes will be made)"; fi
if $AUTO_MODE; then echo "  MODE: AUTO (non-interactive, safe defaults)"; fi
echo "============================================================"
echo ""

log "Checking disk usage..."
DISK_PCT=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
DISK_AVAIL=$(df -h / | awk 'NR==2 {print $4}')
echo "  Disk usage: ${DISK_PCT}% (${DISK_AVAIL} available)"
echo ""

if (( DISK_PCT < DISK_WARN_PCT )); then
    echo "  Disk usage is below ${DISK_WARN_PCT}% — no urgent cleanup needed."
    if ! $AUTO_MODE && ! $DRY_RUN; then
        confirm "  Continue anyway?" || { echo "Exiting."; exit 0; }
    elif $AUTO_MODE; then
        log "Auto mode: disk below threshold, skipping cleanup."
        exit 0
    fi
fi
echo ""

# ── Step 1: Check sizes ──

log "Scanning directory sizes..."
echo ""

FREED=0

dir_size_bytes() {
    if [[ -d "$1" ]]; then
        du -sb "$1" 2>/dev/null | awk '{print $1}'
    else
        echo "0"
    fi
}

RAW_SIZE=$(dir_size_bytes "$RAW_DIR")
PARQUET_SIZE=$(dir_size_bytes "$PARQUET_DIR")
DUCKDB_SIZE=0
if [[ -f "$DUCKDB_PATH" ]]; then
    DUCKDB_SIZE=$(stat -c%s "$DUCKDB_PATH" 2>/dev/null || stat -f%z "$DUCKDB_PATH" 2>/dev/null || echo 0)
fi
ARTIFACTS_SIZE=$(dir_size_bytes "$ARTIFACTS_DIR")
GIT_SIZE=$(dir_size_bytes "$GIT_DIR")

echo "  Raw CSVs:     $(human_size $RAW_SIZE)   ($RAW_DIR)"
echo "  Parquet:      $(human_size $PARQUET_SIZE)   ($PARQUET_DIR)"
echo "  DuckDB:       $(human_size $DUCKDB_SIZE)   ($DUCKDB_PATH)"
echo "  Artifacts:    $(human_size $ARTIFACTS_SIZE)   ($ARTIFACTS_DIR)"
echo "  Git objects:  $(human_size $GIT_SIZE)   ($GIT_DIR)"
echo ""

# ── Step 2: Archive old raw CSVs ──

log "Step 1/5: Archive raw CSVs older than ${RAW_CSV_MAX_AGE_DAYS} days..."

if [[ -d "$RAW_DIR" ]]; then
    OLD_FILES=$(find "$RAW_DIR" -name "*.csv" -type f -mtime +${RAW_CSV_MAX_AGE_DAYS} 2>/dev/null || true)
    OLD_COUNT=$(echo "$OLD_FILES" | grep -c '.' 2>/dev/null || echo 0)
    if [[ -n "$OLD_FILES" && "$OLD_COUNT" -gt 0 ]]; then
        OLD_SIZE=$(echo "$OLD_FILES" | xargs du -cb 2>/dev/null | tail -1 | awk '{print $1}')
        echo "  Found $OLD_COUNT CSVs older than ${RAW_CSV_MAX_AGE_DAYS} days ($(human_size ${OLD_SIZE:-0}))"

        if $DRY_RUN; then
            echo "  [DRY RUN] Would archive to $ARCHIVE_DIR"
        elif confirm "  Archive these to $ARCHIVE_DIR?"; then
            mkdir -p "$ARCHIVE_DIR"
            echo "$OLD_FILES" | while read -r f; do
                mv "$f" "$ARCHIVE_DIR/"
            done
            FREED=$((FREED + ${OLD_SIZE:-0}))
            log "  Archived $OLD_COUNT files."
        else
            echo "  Skipped."
        fi
    else
        echo "  No CSVs older than ${RAW_CSV_MAX_AGE_DAYS} days."
    fi
else
    echo "  Raw directory not found — skipped."
fi
echo ""

# ── Step 3: Vacuum DuckDB ──

log "Step 2/5: Vacuum DuckDB..."

if [[ -f "$DUCKDB_PATH" ]]; then
    BEFORE_SIZE=$DUCKDB_SIZE
    if $DRY_RUN; then
        echo "  [DRY RUN] Would run VACUUM on $DUCKDB_PATH"
    elif confirm "  Run VACUUM on DuckDB ($(human_size $DUCKDB_SIZE))?"; then
        # Check if duckdb CLI is available
        if command -v duckdb &>/dev/null; then
            duckdb "$DUCKDB_PATH" "VACUUM;" 2>/dev/null
            AFTER_SIZE=$(stat -c%s "$DUCKDB_PATH" 2>/dev/null || stat -f%z "$DUCKDB_PATH" 2>/dev/null || echo $BEFORE_SIZE)
            SAVED=$((BEFORE_SIZE - AFTER_SIZE))
            if (( SAVED > 0 )); then
                FREED=$((FREED + SAVED))
                log "  Vacuumed: saved $(human_size $SAVED)"
            else
                log "  Already compact — no space saved."
            fi
        else
            echo "  duckdb CLI not found — skipping. Install with: pip install duckdb-cli"
        fi
    else
        echo "  Skipped."
    fi
else
    echo "  DuckDB not found — skipped."
fi
echo ""

# ── Step 4: Git garbage collection ──

log "Step 3/5: Git garbage collection..."

if [[ -d "$GIT_DIR" ]]; then
    if $DRY_RUN; then
        echo "  [DRY RUN] Would run 'git gc --aggressive' in $REPO_ROOT"
    elif confirm "  Run 'git gc --aggressive' (git objects: $(human_size $GIT_SIZE))?"; then
        BEFORE_SIZE=$GIT_SIZE
        cd "$REPO_ROOT" && git gc --aggressive --quiet 2>/dev/null
        cd "$SCRIPT_DIR"
        AFTER_SIZE=$(dir_size_bytes "$GIT_DIR")
        SAVED=$((BEFORE_SIZE - AFTER_SIZE))
        if (( SAVED > 0 )); then
            FREED=$((FREED + SAVED))
            log "  Git GC: saved $(human_size $SAVED)"
        else
            log "  Already compact — no space saved."
        fi
    else
        echo "  Skipped."
    fi
else
    echo "  Git directory not found — skipped."
fi
echo ""

# ── Step 5: Truncate old logs ──

log "Step 4/5: Truncate log files..."

LOG_TOTAL=0
for f in $LOG_FILES; do
    if [[ -f "$f" ]]; then
        FSIZE=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo 0)
        LOG_TOTAL=$((LOG_TOTAL + FSIZE))
    fi
done

if (( LOG_TOTAL > 0 )); then
    echo "  Log files total: $(human_size $LOG_TOTAL)"
    if $DRY_RUN; then
        echo "  [DRY RUN] Would truncate log files"
    elif confirm "  Truncate all .log files in Daluyan_V2/?"; then
        for f in $LOG_FILES; do
            if [[ -f "$f" ]]; then
                > "$f"
            fi
        done
        FREED=$((FREED + LOG_TOTAL))
        log "  Truncated log files."
    else
        echo "  Skipped."
    fi
else
    echo "  No log files found."
fi
echo ""

# ── Step 6: Prune old artifact backups ──

log "Step 5/5: Check artifact backups..."

BACKUP_DIR="$ARTIFACTS_DIR/backups"
if [[ -d "$BACKUP_DIR" ]]; then
    BACKUP_COUNT=$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)
    BACKUP_SIZE=$(dir_size_bytes "$BACKUP_DIR")
    echo "  Found $BACKUP_COUNT backup(s) ($(human_size $BACKUP_SIZE))"

    if (( BACKUP_COUNT > 2 )); then
        # Keep the 2 most recent, offer to remove older ones
        OLD_BACKUPS=$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d | sort | head -n -2)
        OLD_COUNT=$(echo "$OLD_BACKUPS" | grep -c '.' 2>/dev/null || echo 0)
        if [[ -n "$OLD_BACKUPS" && "$OLD_COUNT" -gt 0 ]]; then
            OLD_BK_SIZE=0
            while read -r d; do
                S=$(dir_size_bytes "$d")
                OLD_BK_SIZE=$((OLD_BK_SIZE + S))
            done <<< "$OLD_BACKUPS"

            echo "  $OLD_COUNT older backup(s) can be removed ($(human_size $OLD_BK_SIZE))"
            echo "  Keeping the 2 most recent backups."

            if $DRY_RUN; then
                echo "  [DRY RUN] Would remove $OLD_COUNT old backup(s)"
            elif confirm "  Remove $OLD_COUNT old backup(s)?"; then
                echo "$OLD_BACKUPS" | while read -r d; do
                    rm -rf "$d"
                done
                FREED=$((FREED + OLD_BK_SIZE))
                log "  Removed $OLD_COUNT old backup(s)."
            else
                echo "  Skipped."
            fi
        fi
    else
        echo "  Only $BACKUP_COUNT backup(s) — keeping all."
    fi
else
    echo "  No backup directory found."
fi
echo ""

# ── Summary ──

echo "============================================================"
echo "  Cleanup complete!"
echo "  Space freed: $(human_size $FREED)"
NEW_PCT=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
NEW_AVAIL=$(df -h / | awk 'NR==2 {print $4}')
echo "  Disk now: ${NEW_PCT}% (${NEW_AVAIL} available)"
echo "============================================================"
