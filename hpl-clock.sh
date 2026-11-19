#!/bin/bash
# MPICH Hydra sets MPI_LOCALRANKID independently on each host.
if [[ ${MPI_LOCALRANKID:?missing MPICH local rank} != 0 ]]; then
    exec ./xhpl
fi

# Sample CPU0's reported frequency while this node's HPL process runs.
host=$(hostname)
cpufreq=/sys/devices/system/cpu/cpu0/cpufreq
./xhpl <&0 &
worker=$!
while kill -0 "$worker" 2>/dev/null; do
    if read -r khz < "$cpufreq/scaling_cur_freq" && [[ $khz =~ ^[1-9][0-9]*$ ]]; then
        echo "HPL_CLOCK $host $khz"
    else
        echo "HPL_CLOCK_ERROR $host scaling_cur_freq"
        break
    fi
    sleep 1
done
wait "$worker"
