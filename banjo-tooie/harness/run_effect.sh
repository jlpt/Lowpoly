#!/bin/sh
# Resumable driver for t_effect.py. If the emulator stops producing frames (t_effect exits 3,
# almost always the game itself crashing) that slot is recorded as CRASH/HANG and the run
# continues with the next slot. Any other failure stops the driver.
# usage: run_effect.sh ROOMSTATE OUT MODE LO HI
STATE=$1 OUT=$2 MODE=$3 LO=$4 HI=$5
i=$LO
while [ $i -le $HI ]; do
  rm -f $OUT.cur
  timeout 7200 python3 -u t_effect.py $STATE $OUT $MODE $i-$HI > $OUT.log 2>&1
  rc=$?
  last=$(tail -n 1 $OUT 2>/dev/null | awk '{print $1}')
  cur=$(cat $OUT.cur 2>/dev/null)
  if [ $rc -eq 3 ] && [ -n "$cur" ] && [ "$cur" != "$last" ]; then
    echo "$cur glitches=$((256 - cur)) | CRASH/HANG (emulator stopped producing frames)" >> $OUT
    last=$cur
  elif [ $rc -ne 0 ]; then
    echo "driver: t_effect exited $rc at slot ${cur:-?}, see $OUT.log" >&2
    [ "$cur" = "$last" ] || break
  fi
  [ -z "$last" ] && break
  i=$((last + 1))
done
rm -f $OUT.cur
