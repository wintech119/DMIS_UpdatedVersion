#!/bin/bash
# =============================================================================
# DMIS Security Static Analysis Script
# =============================================================================
# This script runs Bandit and Semgrep security scanners against the DMIS
# Flask/PostgreSQL codebase. It is designed to:
#   - Install tools if not present
#   - Run both scanners with project-specific configurations
#   - Exit with non-zero status if Critical/High issues are found
#   - Generate reports in multiple formats
#
# Usage:
#   ./scripts/run_sast.sh           # Run full scan
#   ./scripts/run_sast.sh --quick   # Quick scan (errors only)
#   ./scripts/run_sast.sh --report  # Generate HTML/JSON reports
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
BANDIT_CONFIG="${PROJECT_DIR}/bandit.yml"
SEMGREP_CONFIG="${PROJECT_DIR}/semgrep.yml"
REPORT_DIR="${PROJECT_DIR}/security-reports"

# Counters for results
BANDIT_HIGH=0
BANDIT_MEDIUM=0
BANDIT_LOW=0
SEMGREP_ERROR=0
SEMGREP_WARNING=0
SEMGREP_INFO=0

# Parse command line arguments
QUICK_MODE=false
GENERATE_REPORTS=false
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --quick) QUICK_MODE=true ;;
        --report) GENERATE_REPORTS=true ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --quick    Run quick scan (high severity only)"
            echo "  --report   Generate HTML/JSON reports"
            echo "  --help     Show this help message"
            exit 0
            ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  DMIS Security Static Analysis${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# -----------------------------------------------------------------------------
# Step 1: Check and Install Dependencies
# -----------------------------------------------------------------------------
echo -e "${BLUE}[1/4] Checking dependencies...${NC}"

install_bandit() {
    echo -e "${YELLOW}Installing Bandit...${NC}"
    pip install bandit --quiet
}

install_semgrep() {
    echo -e "${YELLOW}Installing Semgrep...${NC}"
    pip install semgrep --quiet
}

# Check for Bandit
if ! command -v bandit &> /dev/null; then
    install_bandit
else
    echo -e "${GREEN}✓ Bandit is installed${NC}"
fi

# Check for Semgrep
if ! command -v semgrep &> /dev/null; then
    install_semgrep
else
    echo -e "${GREEN}✓ Semgrep is installed${NC}"
fi

# Create reports directory if needed
if [ "$GENERATE_REPORTS" = true ]; then
    mkdir -p "$REPORT_DIR"
    echo -e "${GREEN}✓ Reports directory: $REPORT_DIR${NC}"
fi

echo ""

# -----------------------------------------------------------------------------
# Step 2: Run Bandit Security Scanner
# -----------------------------------------------------------------------------
echo -e "${BLUE}[2/4] Running Bandit security scanner...${NC}"

BANDIT_ARGS=""

# Add config file if it exists
if [ -f "$BANDIT_CONFIG" ]; then
    BANDIT_ARGS="-c $BANDIT_CONFIG"
fi

# Quick mode: only high severity
if [ "$QUICK_MODE" = true ]; then
    BANDIT_ARGS="$BANDIT_ARGS -ll"  # Only HIGH severity
fi

# Generate reports if requested
if [ "$GENERATE_REPORTS" = true ]; then
    echo "Generating Bandit reports..."
    bandit -r app/ drims_app.py $BANDIT_ARGS -f json -o "$REPORT_DIR/bandit-report.json" 2>/dev/null || true
    bandit -r app/ drims_app.py $BANDIT_ARGS -f html -o "$REPORT_DIR/bandit-report.html" 2>/dev/null || true
fi

# Run Bandit and capture output
BANDIT_OUTPUT=$(bandit -r app/ drims_app.py $BANDIT_ARGS 2>&1) || true

# Count severity levels from Bandit output (case-insensitive)
BANDIT_HIGH=$(echo "$BANDIT_OUTPUT" | grep -ci "Severity: High" || echo "0")
BANDIT_MEDIUM=$(echo "$BANDIT_OUTPUT" | grep -ci "Severity: Medium" || echo "0")
BANDIT_LOW=$(echo "$BANDIT_OUTPUT" | grep -ci "Severity: Low" || echo "0")

echo "$BANDIT_OUTPUT"
echo ""

if [ "$BANDIT_HIGH" -gt 0 ]; then
    echo -e "${RED}✗ Bandit found $BANDIT_HIGH HIGH severity issues${NC}"
elif [ "$BANDIT_MEDIUM" -gt 0 ]; then
    echo -e "${YELLOW}! Bandit found $BANDIT_MEDIUM MEDIUM severity issues${NC}"
else
    echo -e "${GREEN}✓ Bandit scan completed - no high/medium issues${NC}"
fi

echo ""

# -----------------------------------------------------------------------------
# Step 3: Run Semgrep Security Scanner
# -----------------------------------------------------------------------------
echo -e "${BLUE}[3/4] Running Semgrep security scanner...${NC}"

# Build Semgrep arguments - flags first, then targets
SEMGREP_BASE_ARGS="--config $SEMGREP_CONFIG --config p/python --config p/flask"

# Quick mode: only errors
if [ "$QUICK_MODE" = true ]; then
    SEMGREP_BASE_ARGS="$SEMGREP_BASE_ARGS --severity ERROR"
fi

# Generate reports if requested (run separately to avoid argument order issues)
if [ "$GENERATE_REPORTS" = true ]; then
    echo "Generating Semgrep reports..."
    semgrep $SEMGREP_BASE_ARGS --json --output "$REPORT_DIR/semgrep-report.json" app/ drims_app.py 2>/dev/null || true
fi

# Run Semgrep and capture output to a temp file for proper parsing
SEMGREP_TEMP=$(mktemp)
semgrep $SEMGREP_BASE_ARGS --json app/ drims_app.py > "$SEMGREP_TEMP" 2>&1 || true

# Parse JSON output to count severities accurately
if command -v python3 &> /dev/null; then
    SEMGREP_COUNTS=$(python3 -c "
import json
import sys
try:
    with open('$SEMGREP_TEMP', 'r') as f:
        data = json.load(f)
    results = data.get('results', [])
    error_count = sum(1 for r in results if r.get('extra', {}).get('severity', '').upper() == 'ERROR')
    warning_count = sum(1 for r in results if r.get('extra', {}).get('severity', '').upper() == 'WARNING')
    info_count = sum(1 for r in results if r.get('extra', {}).get('severity', '').upper() == 'INFO')
    print(f'{error_count} {warning_count} {info_count}')
except Exception as e:
    print('0 0 0')
" 2>/dev/null || echo "0 0 0")
    
    SEMGREP_ERROR=$(echo "$SEMGREP_COUNTS" | cut -d' ' -f1)
    SEMGREP_WARNING=$(echo "$SEMGREP_COUNTS" | cut -d' ' -f2)
    SEMGREP_INFO=$(echo "$SEMGREP_COUNTS" | cut -d' ' -f3)
else
    # Fallback: grep for severities (case-insensitive)
    SEMGREP_ERROR=$(grep -ci '"severity":\s*"ERROR"' "$SEMGREP_TEMP" || echo "0")
    SEMGREP_WARNING=$(grep -ci '"severity":\s*"WARNING"' "$SEMGREP_TEMP" || echo "0")
    SEMGREP_INFO=$(grep -ci '"severity":\s*"INFO"' "$SEMGREP_TEMP" || echo "0")
fi

# Also run text output for display
semgrep $SEMGREP_BASE_ARGS app/ drims_app.py 2>&1 || true

# Clean up temp file
rm -f "$SEMGREP_TEMP"

echo ""

if [ "$SEMGREP_ERROR" -gt 0 ]; then
    echo -e "${RED}✗ Semgrep found $SEMGREP_ERROR ERROR severity issues${NC}"
elif [ "$SEMGREP_WARNING" -gt 0 ]; then
    echo -e "${YELLOW}! Semgrep found $SEMGREP_WARNING WARNING severity issues${NC}"
else
    echo -e "${GREEN}✓ Semgrep scan completed - no error/warning issues${NC}"
fi

echo ""

# -----------------------------------------------------------------------------
# Step 4: Summary and Exit Code
# -----------------------------------------------------------------------------
echo -e "${BLUE}[4/4] Security Scan Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Bandit Results:"
echo -e "  HIGH:   $BANDIT_HIGH"
echo -e "  MEDIUM: $BANDIT_MEDIUM"
echo -e "  LOW:    $BANDIT_LOW"
echo ""
echo "Semgrep Results:"
echo -e "  ERROR:   $SEMGREP_ERROR"
echo -e "  WARNING: $SEMGREP_WARNING"
echo -e "  INFO:    $SEMGREP_INFO"
echo ""

if [ "$GENERATE_REPORTS" = true ]; then
    echo -e "${BLUE}Reports generated in: $REPORT_DIR${NC}"
    ls -la "$REPORT_DIR" 2>/dev/null || true
    echo ""
fi

# Determine exit code
# Critical/High issues = fail build (exit 1)
# Medium/Warning = pass with warnings (exit 0)
CRITICAL_COUNT=$((BANDIT_HIGH + SEMGREP_ERROR))

if [ "$CRITICAL_COUNT" -gt 0 ]; then
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}  FAILED: $CRITICAL_COUNT Critical/High issues found${NC}"
    echo -e "${RED}========================================${NC}"
    exit 1
else
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  PASSED: No Critical/High issues found${NC}"
    echo -e "${GREEN}========================================${NC}"
    exit 0
fi
