#!/bin/bash
# Downloads session zips from S3 and extracts them to workspaces/.
# Usage:
#   ./sync-sessions.sh              — sync all sessions from S3
#   ./sync-sessions.sh <filename>   — sync one specific session zip by filename
#
# A session is skipped if its workspace directory already exists.
# The original zip is kept in sessions/ as the immutable source of truth.

set -e
BUCKET="visual-navigation-sessions"
SESSIONS_DIR="/home/ubuntu/lab/sessions"
WORKSPACES_DIR="/home/ubuntu/lab/workspaces"
LOG="/home/ubuntu/lab/sync-sessions.log"
MIN_FREE_GB=5

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

check_disk_space() {
  local free_kb
  free_kb=$(df --output=avail "$SESSIONS_DIR" | tail -1)
  local free_gb=$(( free_kb / 1024 / 1024 ))
  log "Disk free: ${free_gb} GB (minimum required: ${MIN_FREE_GB} GB)"
  if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    log "ERROR: insufficient disk space — ${free_gb} GB free, need at least ${MIN_FREE_GB} GB. Aborting."
    exit 1
  fi
}

process_session() {
  local basename="$1"
  local uuid="${basename#session_}"
  uuid="${uuid%.zip}"
  local workspace="$WORKSPACES_DIR/$uuid"

  if [ -d "$workspace" ]; then
    log "SKIP $basename — workspace already exists"
    return
  fi

  if [ ! -f "$SESSIONS_DIR/$basename" ]; then
    log "DOWNLOAD $basename"
    aws s3 cp "s3://$BUCKET/sessions/$basename" "$SESSIONS_DIR/$basename"
  else
    log "ALREADY DOWNLOADED $basename"
  fi

  log "EXTRACT $basename → workspaces/$uuid/"
  mkdir -p "$workspace"
  unzip -q "$SESSIONS_DIR/$basename" -d "$workspace"
  log "DONE $basename"
}

check_disk_space

if [ -n "$1" ]; then
  process_session "$(basename "$1")"
else
  log "Listing sessions in s3://$BUCKET/sessions/"
  aws s3 ls "s3://$BUCKET/sessions/" --recursive \
    | awk '{print $4}' \
    | grep '\.zip$' \
    | while read key; do
        process_session "$(basename "$key")"
      done
  log "Sync complete"
fi
