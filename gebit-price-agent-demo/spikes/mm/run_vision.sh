#!/bin/bash
# usage: run_vision.sh <image> <model> <task> <runs>
D=$(cd "$(dirname "$0")" && pwd)
B=$(mktemp "$D/body.XXXX")
DUMP_BODY=$B python3 -I "$D/probe_vision.py" "$1" "$2" "$3"
for i in $(seq 1 "$4"); do
  R=$(curl -s -m 120 -H "Authorization: Bearer $LLM_SERVICE_API_KEY" -H "Content-Type: application/json" \
     --data-binary @"$B" https://lite-llm.mymaas.net/v1/chat/completions -w '\n%{http_code} %{time_total}')
  CODE_T=$(printf '%s' "$R" | tail -1)
  BODY=$(printf '%s' "$R" | sed '$d')
  printf '%s' "$BODY" | python3 -I -c "
import json,sys
code,t='$CODE_T'.split()
try:
  r=json.load(sys.stdin)
  u=r.get('usage',{})
  ans=r['choices'][0]['message']['content'] if 'choices' in r else json.dumps(r)[:300]
except Exception as e:
  u={}; ans='parse error '+repr(e)
print(json.dumps({'model':'$2','task':'$3','run':$i,'http':code,'secs':float(t),'prompt_tokens':u.get('prompt_tokens'),'completion_tokens':u.get('completion_tokens'),'answer':(ans or '').strip()[:320]},ensure_ascii=False))"
done
rm -f "$B"
