#!/usr/bin/env bash
# Trigger the MoneyPrinterTurbo API workflow from cron.
# Oracle Linux 8: install this file with mode 0750 and run it as the same user
# that owns the MoneyPrinterTurbo service.
set -u

API_URL="${MPT_API_URL:-http://127.0.0.1:8080/api/v1/generate}"
VIDEO_LANGUAGE="${MPT_VIDEO_LANGUAGE:-en-US}"
# Leave empty when the API is running with its current unauthenticated router.
# If API-key authentication is enabled, set MPT_API_KEY in this file or the
# cron environment before running the job.
API_KEY="${MPT_API_KEY:-}"

LOG_FILE="${MPT_CRON_LOG:-/home/opc/projekty/MoneyPrinterTurbo/storage/logs/cron-generate.log}"
mkdir -p "$(dirname "$LOG_FILE")"

payload=$(cat <<JSON
{
  "video_subject": "",
  "roll_next_subject": true,
  "based_on_recent": true,
  "video_language": "${VIDEO_LANGUAGE}"
}
JSON
)

printf '[%s] starting API generation request: %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$API_URL" >>"$LOG_FILE"

curl_args=(
  --silent
  --show-error
  --fail
  --connect-timeout 10
  --max-time 180
  --request POST
  --header 'Content-Type: application/json'
  --data "$payload"
  "$API_URL"
)
if [[ -n "$API_KEY" ]]; then
  curl_args=(
    --silent
    --show-error
    --fail
    --connect-timeout 10
    --max-time 180
    --request POST
    --header 'Content-Type: application/json'
    --header "x-api-key: $API_KEY"
    --data "$payload"
    "$API_URL"
  )
fi

if response=$(/usr/bin/curl "${curl_args[@]}" 2>&1); then
  printf '[%s] API request accepted: %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$response" >>"$LOG_FILE"
  exit 0
else
  status=$?
  printf '[%s] API request failed with exit code %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$status" "$response" >>"$LOG_FILE"
  exit "$status"
fi
