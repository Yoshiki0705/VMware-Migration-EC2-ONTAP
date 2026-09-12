#!/bin/bash
# ==============================================================================
# FSx for ONTAP iSCSI Benchmark Script
# Purpose: Measure iSCSI LUN performance on FSx for ONTAP attached to EC2
# Usage:   ./fio-benchmark.sh /dev/sdX [output_dir]
#
# Prerequisites:
#   - fio installed (sudo yum install -y fio OR sudo apt install -y fio)
#   - Target device is an FSx for ONTAP iSCSI LUN (NOT the OS disk!)
#   - EC2 instance type and FSx for ONTAP config documented before running
#
# WARNING: This script writes directly to the block device. ALL DATA WILL BE LOST.
#          Only use on dedicated test LUNs with no production data.
#
# WARNING: A thin-provisioned LUN returns zeros for blocks that were never written, without
#          reaching disk. Measuring reads before a full write pass measures nothing. Write the
#          whole device once first.
#
# MEASUREMENT TOOL: fio. The perf-matrix figures in the sibling repository
#          S3-Burst-on-ONTAP-Files are measured with VDBENCH 5.04.07 directly, so the two sets
#          cannot be placed in the same table -- the measurement tool differs. If they need to be
#          compared, switch this side to VDBENCH rather than converting the numbers.
#
#          That repository's block measurements (iSCSI and NVMe/TCP, patterns F-1 to F-3) are
#          planned and NOT YET RUN, so there is nothing to compare against yet either:
#          docs/ja/verification/block-protocol-matrix-plan.md
# ==============================================================================

set -euo pipefail

# ---------- Configuration ----------
DEVICE="${1:-}"
OUTPUT_DIR="${2:-./benchmark-results}"
RUNTIME=300        # seconds per test
RAMP_TIME=30       # warmup before measurement
SIZE="10G"         # test file size (only for file-based tests)
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# ---------- Validation ----------
if [[ -z "$DEVICE" ]]; then
    echo "Usage: $0 <device_path> [output_dir]"
    echo "Example: $0 /dev/sdb ./benchmark-results"
    echo ""
    echo "WARNING: This will DESTROY all data on the target device!"
    exit 1
fi

if [[ ! -b "$DEVICE" ]]; then
    echo "ERROR: $DEVICE is not a block device"
    exit 1
fi

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  FSx for ONTAP iSCSI Benchmark                             ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Target Device: $DEVICE"
echo "║  Output Dir:    $OUTPUT_DIR"
echo "║  Runtime:       ${RUNTIME}s per test (+ ${RAMP_TIME}s ramp)"
echo "║  Timestamp:     $TIMESTAMP"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "⚠️  WARNING: ALL DATA on $DEVICE WILL BE DESTROYED!"
echo ""
read -rp "Type 'YES' to continue: " CONFIRM
if [[ "$CONFIRM" != "YES" ]]; then
    echo "Aborted."
    exit 0
fi

# ---------- Setup ----------
mkdir -p "$OUTPUT_DIR"

# Collect environment metadata
ENV_FILE="$OUTPUT_DIR/environment-${TIMESTAMP}.json"
echo "📋 Collecting environment metadata..."

cat > "$ENV_FILE" << EOF
{
  "benchmark_run_id": "fsxn-iscsi-${TIMESTAMP}",
  "timestamp": "$TIMESTAMP",
  "device": "$DEVICE",
  "hostname": "$(hostname)",
  "instance_type": "$(curl -s http://169.254.169.254/latest/meta-data/instance-type 2>/dev/null || echo 'unknown')",
  "instance_id": "$(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo 'unknown')",
  "az": "$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone 2>/dev/null || echo 'unknown')",
  "kernel": "$(uname -r)",
  "fio_version": "$(fio --version 2>/dev/null || echo 'unknown')",
  "iscsi_sessions": $(iscsiadm -m session 2>/dev/null | wc -l || echo 0),
  "multipath_paths": "$(multipath -ll 2>/dev/null | grep -c 'active ready' || echo 'unknown')",
  "device_size_gb": $(lsblk -bno SIZE "$DEVICE" 2>/dev/null | awk '{printf "%.1f", $1/1024/1024/1024}' || echo 0),
  "runtime_seconds": $RUNTIME,
  "ramp_time_seconds": $RAMP_TIME,
  "notes": "SIZING REFERENCE ONLY. Not a service limit. Performance varies by workload, network, and FSx for ONTAP configuration."
}
EOF

echo "✅ Environment metadata saved to $ENV_FILE"
echo ""

# ---------- Benchmark Functions ----------
run_fio() {
    local TEST_NAME="$1"
    local BS="$2"
    local IODEPTH="$3"
    local RW="$4"
    local NUMJOBS="${5:-4}"
    local OUTPUT_FILE="$OUTPUT_DIR/${TEST_NAME}-${TIMESTAMP}.json"

    echo "🔄 Running: $TEST_NAME (bs=$BS, iodepth=$IODEPTH, rw=$RW, numjobs=$NUMJOBS)"
    echo "   Duration: ${RAMP_TIME}s ramp + ${RUNTIME}s measurement"

    fio \
        --name="$TEST_NAME" \
        --filename="$DEVICE" \
        --ioengine=libaio \
        --direct=1 \
        --bs="$BS" \
        --iodepth="$IODEPTH" \
        --numjobs="$NUMJOBS" \
        --rw="$RW" \
        --size="$SIZE" \
        --runtime="$RUNTIME" \
        --time_based \
        --ramp_time="$RAMP_TIME" \
        --group_reporting \
        --output-format=json \
        --output="$OUTPUT_FILE"

    echo "   ✅ Results: $OUTPUT_FILE"
    echo ""
}

# ---------- Execute Benchmark Suite ----------
echo "════════════════════════════════════════════════════════════════"
echo "  Starting Benchmark Suite (4 tests × ${RUNTIME}s = ~$((RUNTIME * 4 / 60)) min total)"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Test 1: 4K Random Read — measures IOPS capability
run_fio "4k-randread" "4k" "64" "randread" "4"

# Test 2: 4K Random Write — measures write IOPS
run_fio "4k-randwrite" "4k" "64" "randwrite" "4"

# Test 3: 64K Sequential Read — measures throughput
run_fio "64k-seqread" "64k" "32" "read" "4"

# Test 4: 64K Sequential Write — measures write throughput
run_fio "64k-seqwrite" "64k" "32" "write" "4"

# ---------- Summary ----------
echo "════════════════════════════════════════════════════════════════"
echo "  Benchmark Complete!"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Results directory: $OUTPUT_DIR"
echo "Run ID: fsxn-iscsi-${TIMESTAMP}"
echo ""
echo "Files generated:"
ls -la "$OUTPUT_DIR"/*"$TIMESTAMP"*
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚠️  IMPORTANT: These results are a SIZING REFERENCE for this"
echo "    specific test environment. They do NOT represent FSx for"
echo "    ONTAP service limits. Actual performance depends on:"
echo "    - FSx for ONTAP provisioned throughput & SSD capacity"
echo "    - Flash Cache availability and working set size"
echo "    - EC2 instance type network bandwidth"
echo "    - iSCSI session count and multipath configuration"
echo "    - Workload characteristics (block size, queue depth, R/W mix)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
