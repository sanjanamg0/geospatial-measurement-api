#!/usr/bin/env bash
# End-to-end check of a running API with GEO_ASYNC set: upload a sample, poll until the
# background worker finishes, then check the summary and a bounding-box filter.
#   scripts/smoke_async.sh [base_url] [token]
set -euo pipefail

BASE="${1:-http://localhost:8000}"
TOKEN="${2:-}"
AUTH=()
[ -n "$TOKEN" ] && AUTH=(-H "Authorization: Token $TOKEN")
SAMPLE="$(dirname "$0")/../samples/qgis_check.kml"

json() { python -c "import sys, json; d = json.load(sys.stdin); print($1)"; }

response=$(curl -sf "${AUTH[@]}" -F "file=@$SAMPLE" "$BASE/api/files/")
id=$(echo "$response" | json "d['id']")
echo "uploaded $id, initial status: $(echo "$response" | json "d['status']")"

for _ in $(seq 1 30); do
  status=$(curl -sf "${AUTH[@]}" "$BASE/api/files/$id/" | json "d['status']")
  [ "$status" = COMPLETED ] || [ "$status" = FAILED ] && break
  sleep 1
done
echo "final status: $status"
[ "$status" = COMPLETED ] || { echo "processing did not complete"; exit 1; }

inside=$(curl -sf "${AUTH[@]}" "$BASE/api/files/$id/measurements/?bbox=77.59,12.97,77.595,12.975" | json "d['count']")
outside=$(curl -sf "${AUTH[@]}" "$BASE/api/files/$id/measurements/?bbox=10,10,11,11" | json "d['count']")
echo "features inside bbox: $inside, outside bbox: $outside"
[ "$inside" = 2 ] && [ "$outside" = 0 ] || { echo "unexpected bbox result"; exit 1; }
echo "OK"
