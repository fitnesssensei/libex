#!/bin/bash
# Живой таймер: сколько секунд осталось до старта каждого процесса "sleep NNNN".
# Выход по Ctrl+C.

# zapusk: ./timer.sh
# cd /Users/rustamismagilov/Desktop/Libex
# ./timer.sh

while true; do
  clear
  echo "=== Остаток до старта (секунды) — $(date '+%H:%M:%S')  [Ctrl+C — выход] ==="
  echo "PID      TTY        осталось (сек)   итого   прошло"
  echo "----------------------------------------------------------"
  ps -eo pid,etime,tt,args \
    | grep -E ' sleep [0-9]+' \
    | grep -vE 'bash -c|grep|timer\.sh' \
    | while read -r pid et tt etcmd; do
        total=$(echo "$etcmd" | grep -oE 'sleep [0-9]+' | grep -oE '[0-9]+')
        [ -z "$total" ] && continue
        days=0
        rest="$et"
        case "$et" in
          *-*) days=$(( ${et%%-*}+0 )); rest=${et#*-} ;;
        esac
        IFS=: read -r f1 f2 f3 <<< "$rest"
        if [ -n "$f3" ]; then
          el=$(( (10#$f1)*3600 + (10#$f2)*60 + (10#$f3) ))
        else
          el=$(( (10#$f1)*60 + (10#$f2) ))
        fi
        el=$(( days*86400 + el ))
        remain=$(( total - el ))
        tty=$(printf '%s' "$tt" | tr -d ' \ts')
        printf '%-7s  tty%s   %6d            %5d   %6d\n' "$pid" "${tty#s}" "$remain" "$total" "$el"
      done
  sleep 1
done