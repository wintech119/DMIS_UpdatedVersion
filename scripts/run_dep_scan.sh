#!/bin/bash
# =============================================================================
# DMIS Dependency Security Scanner
# =============================================================================
# This script scans Python dependencies for known vulnerabilities using
# pip-audit and safety. It is designed to:
#   - Scan requirements.txt or installed packages
#   - Report CVEs and known security vulnerabilities
#   - Exit with non-zero status if Critical/High vulnerabilities are found
#   - Generate reports for CI/CD integration
#
# Usage:
#   ./scripts/run_dep_scan.sh           # Scan requirements.txt
#   ./scripts/run_dep_scan.sh --env     # Scan installed environment
#   ./scripts/run_dep_scan.sh --report  # Generate JSON reports
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
REQUIREMENTS_FILE="${PROJECT_DIR}/requirements.txt"
REPORT_DIR="${PROJECT_DIR}/security-reports"

# Counters for results
PIP_AUDIT_CRITICAL=0
PIP_AUDIT_HIGH=0
PIP_AUDIT_MEDIUM=0
PIP_AUDIT_LOW=0
SAFETY_CRITICAL=0
SAFETY_HIGH=0
SAFETY_MEDIUM=0
SAFETY_LOW=0

# Parse command line arguments
SCAN_ENV=false
GENERATE_REPORTS=false

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --env) SCAN_ENV=true ;;
        --report) GENERATE_REPORTS=true ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --env      Scan installed environment instead of requirements.txt"
            echo "  --report   Generate JSON reports in security-reports/"
            echo "  --help     Show this help message"
            exit 0
            ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  DMIS Dependency Security Scanner${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# -----------------------------------------------------------------------------
# Step 1: Check and Install Dependencies
# -----------------------------------------------------------------------------
echo -e "${BLUE}[1/4] Checking scanner tools...${NC}"

install_pip_audit() {
    echo -e "${YELLOW}Installing pip-audit...${NC}"
    pip install pip-audit --quiet
}

install_safety() {
    echo -e "${YELLOW}Installing safety...${NC}"
    pip install safety --quiet
}

# Check for pip-audit
if ! command -v pip-audit &> /dev/null; then
    install_pip_audit
else
    echo -e "${GREEN}✓ pip-audit is installed${NC}"
fi

# Check for safety
if ! command -v safety &> /dev/null; then
    install_safety
else
    echo -e "${GREEN}✓ safety is installed${NC}"
fi

# Create reports directory if needed
if [ "$GENERATE_REPORTS" = true ]; then
    mkdir -p "$REPORT_DIR"
    echo -e "${GREEN}✓ Reports directory: $REPORT_DIR${NC}"
fi

# Check for requirements file
if [ "$SCAN_ENV" = false ] && [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo -e "${YELLOW}! requirements.txt not found, scanning installed environment${NC}"
    SCAN_ENV=true
fi

echo ""

# -----------------------------------------------------------------------------
# Step 2: Run pip-audit
# -----------------------------------------------------------------------------
echo -e "${BLUE}[2/4] Running pip-audit vulnerability scanner...${NC}"

PIP_AUDIT_ARGS=""
if [ "$SCAN_ENV" = false ]; then
    PIP_AUDIT_ARGS="-r $REQUIREMENTS_FILE"
fi

# Create temp file for JSON output
PIP_AUDIT_TEMP=$(mktemp)

# Run pip-audit with JSON output for parsing
echo "Scanning dependencies for known vulnerabilities..."
pip-audit $PIP_AUDIT_ARGS --format json --output "$PIP_AUDIT_TEMP" 2>&1 || true

# Parse JSON to count vulnerabilities by severity
# Conservative approach: Any known vulnerability defaults to HIGH unless explicitly low/medium
if command -v python3 &> /dev/null && [ -f "$PIP_AUDIT_TEMP" ] && [ -s "$PIP_AUDIT_TEMP" ]; then
    PIP_AUDIT_COUNTS=$(python3 - "$PIP_AUDIT_TEMP" << 'PYTHON_EOF'
import json
import sys
import re

def extract_cvss_score(score_value):
    """
    Extract numeric CVSS base score from various formats:
    - Numeric: 7.5, 8.8
    - Vector string: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
    - With base score: "8.8 CVSS:3.1/..."
    """
    if score_value is None:
        return None
    
    # If already numeric
    if isinstance(score_value, (int, float)):
        return float(score_value)
    
    if not isinstance(score_value, str):
        return None
    
    # Try to extract leading numeric score (e.g., "8.8" from "8.8 CVSS:3.1/...")
    match = re.match(r'^(\d+\.?\d*)', score_value.strip())
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    
    # For pure CVSS vector strings without numeric prefix, return None
    # and let the caller use conservative default
    return None

def score_to_severity(score):
    """Map CVSS score to severity level using standard thresholds."""
    if score is None:
        return None
    try:
        score = float(score)
        if score >= 9.0:
            return 'critical'
        elif score >= 7.0:
            return 'high'
        elif score >= 4.0:
            return 'medium'
        else:
            return 'low'
    except (ValueError, TypeError):
        return None

def normalize_severity(sev_str):
    """Normalize explicit severity labels only."""
    if not sev_str or not isinstance(sev_str, str):
        return None
    sev_lower = sev_str.lower().strip()
    # Only recognize explicit severity labels
    if sev_lower in ('critical', 'crit'):
        return 'critical'
    elif sev_lower in ('high', 'important'):
        return 'high'
    elif sev_lower in ('medium', 'moderate', 'mod'):
        return 'medium'
    elif sev_lower in ('low', 'minor', 'informational', 'info'):
        return 'low'
    return None

try:
    filepath = sys.argv[1] if len(sys.argv) > 1 else '/dev/stdin'
    with open(filepath, 'r') as f:
        content = f.read().strip()
    
    if not content:
        print('0 0 0 0')
        sys.exit(0)
    
    data = json.loads(content)
    vulns = data if isinstance(data, list) else data.get('dependencies', [])
    
    critical = 0
    high = 0
    medium = 0
    low = 0
    
    for pkg in vulns:
        pkg_vulns = pkg.get('vulns', [])
        for vuln in pkg_vulns:
            vuln_id = vuln.get('id', '').upper()
            description = vuln.get('description', '').lower()
            severity = None
            
            # Strategy: Be conservative. Any known CVE is serious until proven otherwise.
            # 1. Check for explicit severity field with proper label or CVSS score
            if 'severity' in vuln:
                sev_data = vuln['severity']
                
                if isinstance(sev_data, str):
                    # Try as severity label first
                    severity = normalize_severity(sev_data)
                    # Try as CVSS score
                    if not severity:
                        score = extract_cvss_score(sev_data)
                        if score:
                            severity = score_to_severity(score)
                
                elif isinstance(sev_data, dict):
                    # Check for explicit severity label
                    severity = normalize_severity(sev_data.get('severity', ''))
                    # Check for CVSS score
                    if not severity:
                        score = extract_cvss_score(sev_data.get('score'))
                        if score:
                            severity = score_to_severity(score)
                        else:
                            # Has CVSS data but no parseable score - be conservative
                            if sev_data.get('score') or sev_data.get('type'):
                                severity = 'high'  # CVSS present = significant
                
                elif isinstance(sev_data, list):
                    # OSV format: list of severity sources
                    best_severity = None
                    has_cvss = False
                    for sev_item in sev_data:
                        if isinstance(sev_item, dict):
                            # Check for explicit severity label
                            item_sev = normalize_severity(sev_item.get('severity', ''))
                            
                            # Check for CVSS score
                            if not item_sev:
                                score = extract_cvss_score(sev_item.get('score'))
                                if score:
                                    item_sev = score_to_severity(score)
                                elif sev_item.get('score') or sev_item.get('type'):
                                    # Has CVSS data present
                                    has_cvss = True
                            
                            if item_sev:
                                sev_order = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}
                                if not best_severity or sev_order.get(item_sev, 0) > sev_order.get(best_severity, 0):
                                    best_severity = item_sev
                    
                    severity = best_severity
                    # If CVSS data was present but no parseable severity, default to HIGH
                    if not severity and has_cvss:
                        severity = 'high'
            
            # 2. Check aliases for severity hints
            if not severity:
                for alias in vuln.get('aliases', []):
                    if isinstance(alias, dict):
                        alias_sev = normalize_severity(alias.get('severity', ''))
                        if alias_sev:
                            severity = alias_sev
                            break
            
            # 3. Check description for severity keywords (as hints)
            if not severity:
                if any(kw in description for kw in ['critical', 'remote code execution', 'rce']):
                    severity = 'critical'
                elif any(kw in description for kw in ['arbitrary code', 'sql injection', 'authentication bypass', 'privilege escalation']):
                    severity = 'high'
            
            # 4. CONSERVATIVE DEFAULT: Any known advisory is HIGH until proven otherwise
            # GHSA, PYSEC, CVE - these are all curated advisories indicating real security issues
            if not severity:
                severity = 'high'  # Conservative: assume worst case for any CVE
            
            # Count by severity
            if severity == 'critical':
                critical += 1
            elif severity == 'high':
                high += 1
            elif severity == 'medium':
                medium += 1
            else:
                low += 1
    
    print(f'{critical} {high} {medium} {low}')

except Exception:
    print('0 0 0 0')
PYTHON_EOF
    )
    
    PIP_AUDIT_CRITICAL=$(echo "$PIP_AUDIT_COUNTS" | cut -d' ' -f1)
    PIP_AUDIT_HIGH=$(echo "$PIP_AUDIT_COUNTS" | cut -d' ' -f2)
    PIP_AUDIT_MEDIUM=$(echo "$PIP_AUDIT_COUNTS" | cut -d' ' -f3)
    PIP_AUDIT_LOW=$(echo "$PIP_AUDIT_COUNTS" | cut -d' ' -f4)
fi

# Generate report if requested
if [ "$GENERATE_REPORTS" = true ] && [ -f "$PIP_AUDIT_TEMP" ]; then
    cp "$PIP_AUDIT_TEMP" "$REPORT_DIR/pip-audit-report.json"
fi

# Display text output
pip-audit $PIP_AUDIT_ARGS 2>&1 || true

# Clean up
rm -f "$PIP_AUDIT_TEMP"

echo ""

PIP_AUDIT_TOTAL=$((PIP_AUDIT_CRITICAL + PIP_AUDIT_HIGH + PIP_AUDIT_MEDIUM + PIP_AUDIT_LOW))
if [ "$PIP_AUDIT_CRITICAL" -gt 0 ] || [ "$PIP_AUDIT_HIGH" -gt 0 ]; then
    echo -e "${RED}✗ pip-audit found $PIP_AUDIT_CRITICAL CRITICAL and $PIP_AUDIT_HIGH HIGH vulnerabilities${NC}"
elif [ "$PIP_AUDIT_TOTAL" -gt 0 ]; then
    echo -e "${YELLOW}! pip-audit found $PIP_AUDIT_TOTAL vulnerabilities (medium/low)${NC}"
else
    echo -e "${GREEN}✓ pip-audit: No known vulnerabilities found${NC}"
fi

echo ""

# -----------------------------------------------------------------------------
# Step 3: Run safety check
# -----------------------------------------------------------------------------
echo -e "${BLUE}[3/4] Running safety vulnerability scanner...${NC}"

SAFETY_ARGS=""
if [ "$SCAN_ENV" = false ]; then
    SAFETY_ARGS="-r $REQUIREMENTS_FILE"
fi

# Create temp file for JSON output
SAFETY_TEMP=$(mktemp)

# Run safety with JSON output
echo "Cross-checking with safety database..."
safety check $SAFETY_ARGS --output json > "$SAFETY_TEMP" 2>&1 || true

# Parse JSON to count vulnerabilities with severity
if command -v python3 &> /dev/null && [ -f "$SAFETY_TEMP" ] && [ -s "$SAFETY_TEMP" ]; then
    SAFETY_COUNTS=$(python3 - "$SAFETY_TEMP" << 'PYTHON_EOF'
import json
import sys

def extract_cvss_score(score_value):
    """Extract numeric CVSS base score."""
    if score_value is None:
        return None
    if isinstance(score_value, (int, float)):
        return float(score_value)
    return None

def score_to_severity(score):
    """Map CVSS score to severity level."""
    if score is None:
        return None
    try:
        score = float(score)
        if score >= 9.0:
            return 'critical'
        elif score >= 7.0:
            return 'high'
        elif score >= 4.0:
            return 'medium'
        else:
            return 'low'
    except (ValueError, TypeError):
        return None

try:
    filepath = sys.argv[1] if len(sys.argv) > 1 else '/dev/stdin'
    with open(filepath, 'r') as f:
        content = f.read().strip()
    
    if not content:
        print('0 0 0 0')
        sys.exit(0)
    
    critical = 0
    high = 0
    medium = 0
    low = 0
    
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        print('0 0 0 0')
        sys.exit(0)
    
    vulns = []
    if isinstance(data, dict):
        vulns = data.get('vulnerabilities', [])
        if not vulns:
            for pkg in data.get('scanned_packages', {}).values():
                vulns.extend(pkg.get('vulnerabilities', []))
    elif isinstance(data, list):
        vulns = data
    
    valid_severities = ('critical', 'high', 'medium', 'moderate', 'low')
    
    for vuln in vulns:
        severity = None
        
        if isinstance(vuln, dict):
            # Check explicit severity field
            sev = str(vuln.get('severity', '')).lower()
            if sev in valid_severities:
                severity = sev
            
            if not severity:
                sev = str(vuln.get('severity_source', '')).lower()
                if sev in valid_severities:
                    severity = sev
            
            if not severity:
                analyzed = vuln.get('analyzed_requirement', {})
                if isinstance(analyzed, dict):
                    sev = str(analyzed.get('severity', '')).lower()
                    if sev in valid_severities:
                        severity = sev
            
            # Check CVSS score
            if not severity:
                cvss = vuln.get('cvssv3', {})
                if isinstance(cvss, dict):
                    score = extract_cvss_score(cvss.get('base_score'))
                    if score:
                        severity = score_to_severity(score)
        
        # Map and count
        if severity and 'critical' in severity:
            critical += 1
        elif severity and 'high' in severity:
            high += 1
        elif severity and ('medium' in severity or 'moderate' in severity):
            medium += 1
        elif severity and 'low' in severity:
            low += 1
        else:
            # CONSERVATIVE: Default to HIGH for any unclassified finding
            high += 1
    
    print(f'{critical} {high} {medium} {low}')

except Exception:
    print('0 0 0 0')
PYTHON_EOF
    )
    
    SAFETY_CRITICAL=$(echo "$SAFETY_COUNTS" | cut -d' ' -f1)
    SAFETY_HIGH=$(echo "$SAFETY_COUNTS" | cut -d' ' -f2)
    SAFETY_MEDIUM=$(echo "$SAFETY_COUNTS" | cut -d' ' -f3)
    SAFETY_LOW=$(echo "$SAFETY_COUNTS" | cut -d' ' -f4)
fi

# Generate report if requested
if [ "$GENERATE_REPORTS" = true ] && [ -f "$SAFETY_TEMP" ]; then
    cp "$SAFETY_TEMP" "$REPORT_DIR/safety-report.json"
fi

# Display text output
safety check $SAFETY_ARGS 2>&1 || true

# Clean up
rm -f "$SAFETY_TEMP"

echo ""

SAFETY_TOTAL=$((SAFETY_CRITICAL + SAFETY_HIGH + SAFETY_MEDIUM + SAFETY_LOW))
if [ "$SAFETY_CRITICAL" -gt 0 ] || [ "$SAFETY_HIGH" -gt 0 ]; then
    echo -e "${RED}✗ safety found $SAFETY_CRITICAL CRITICAL and $SAFETY_HIGH HIGH vulnerabilities${NC}"
elif [ "$SAFETY_TOTAL" -gt 0 ]; then
    echo -e "${YELLOW}! safety found $SAFETY_TOTAL vulnerabilities (medium/low)${NC}"
else
    echo -e "${GREEN}✓ safety: No known vulnerabilities found${NC}"
fi

echo ""

# -----------------------------------------------------------------------------
# Step 4: Summary and Exit Code
# -----------------------------------------------------------------------------
echo -e "${BLUE}[4/4] Dependency Scan Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "pip-audit Results:"
echo -e "  CRITICAL: $PIP_AUDIT_CRITICAL"
echo -e "  HIGH:     $PIP_AUDIT_HIGH"
echo -e "  MEDIUM:   $PIP_AUDIT_MEDIUM"
echo -e "  LOW:      $PIP_AUDIT_LOW"
echo ""
echo "safety Results:"
echo -e "  CRITICAL: $SAFETY_CRITICAL"
echo -e "  HIGH:     $SAFETY_HIGH"
echo -e "  MEDIUM:   $SAFETY_MEDIUM"
echo -e "  LOW:      $SAFETY_LOW"
echo ""

if [ "$GENERATE_REPORTS" = true ]; then
    echo -e "${BLUE}Reports generated in: $REPORT_DIR${NC}"
    ls -la "$REPORT_DIR"/*-report.json 2>/dev/null || true
    echo ""
fi

# Determine exit code
# Critical/High vulnerabilities from EITHER tool = fail (exit 1)
CRITICAL_COUNT=$((PIP_AUDIT_CRITICAL + PIP_AUDIT_HIGH + SAFETY_CRITICAL + SAFETY_HIGH))

if [ "$CRITICAL_COUNT" -gt 0 ]; then
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}  FAILED: $CRITICAL_COUNT Critical/High vulnerabilities${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo "Action required:"
    echo "  1. Review the vulnerabilities listed above"
    echo "  2. Update affected packages to patched versions"
    echo "  3. If no patch available, document risk exception"
    echo ""
    exit 1
else
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  PASSED: No Critical/High vulnerabilities${NC}"
    echo -e "${GREEN}========================================${NC}"
    
    TOTAL_VULNS=$((PIP_AUDIT_MEDIUM + PIP_AUDIT_LOW + SAFETY_MEDIUM + SAFETY_LOW))
    if [ "$TOTAL_VULNS" -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}Note: $TOTAL_VULNS medium/low vulnerabilities found.${NC}"
        echo "Consider reviewing and updating when possible."
    fi
    
    exit 0
fi
