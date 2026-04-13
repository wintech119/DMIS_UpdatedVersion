#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI/UX Pro Max Search - BM25 search engine for UI/UX style guides
Usage: python search.py "<query>" [--domain <domain>] [--stack <stack>] [--max-results 3]
       python search.py "<query>" --design-system [-p "Project Name"]
       python search.py "<query>" --design-system --persist [-p "Project Name"] [--page "dashboard"]

Domains: style, prompt, color, chart, landing, product, ux, typography
Stacks: html-tailwind, react, nextjs

Persistence (Master + Overrides pattern):
  --persist    Save design system to design-system/<project-slug>/MASTER.md
  --page       Also create a page-specific override file in design-system/<project-slug>/pages/*.md
"""

import argparse
import sys
import io
from pathlib import Path
from core import CSV_CONFIG, AVAILABLE_STACKS, MAX_RESULTS, search, search_stack
from design_system import generate_design_system, persist_design_system

# Force UTF-8 for stdout/stderr to handle emojis on Windows (cp1252 default)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def format_output(result):
    """Format results for Claude consumption (token-optimized)"""
    if "error" in result:
        return f"Error: {result['error']}"

    output = []
    if result.get("stack"):
        output.append("## UI Pro Max Stack Guidelines")
        output.append(f"**Stack:** {result['stack']} | **Query:** {result['query']}")
    else:
        output.append("## UI Pro Max Search Results")
        output.append(f"**Domain:** {result['domain']} | **Query:** {result['query']}")
    output.append(f"**Source:** {result['file']} | **Found:** {result['count']} results\n")

    for i, row in enumerate(result['results'], 1):
        output.append(f"### Result {i}")
        for key, value in row.items():
            value_str = str(value)
            if len(value_str) > 300:
                value_str = value_str[:300] + "..."
            output.append(f"- **{key}:** {value_str}")
        output.append("")

    return "\n".join(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UI Pro Max Search")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--domain", "-d", choices=list(CSV_CONFIG.keys()), help="Search domain")
    parser.add_argument("--stack", "-s", choices=AVAILABLE_STACKS, help="Stack-specific search (html-tailwind, react, nextjs)")
    parser.add_argument("--max-results", "-n", type=int, default=MAX_RESULTS, help="Max results (default: 3)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    # Design system generation
    parser.add_argument("--design-system", "-ds", action="store_true", help="Generate complete design system recommendation")
    parser.add_argument("--project-name", "-p", type=str, default=None, help="Project name for design system output")
    parser.add_argument("--format", "-f", choices=["ascii", "markdown"], default="ascii", help="Output format for design system")
    # Persistence (Master + Overrides pattern)
    parser.add_argument("--persist", action="store_true", help="Save design system to design-system/<project-slug>/MASTER.md (creates hierarchical structure)")
    parser.add_argument("--page", type=str, default=None, help="Create page-specific override file in design-system/<project-slug>/pages/*.md")
    parser.add_argument("--output-dir", "-o", type=str, default=None, help="Output directory for persisted files (default: current directory)")

    args = parser.parse_args()

    if args.design_system:
        invalid_mode_flags = []
        if args.stack:
            invalid_mode_flags.append("--stack")
        if args.domain:
            invalid_mode_flags.append("--domain")
        if args.json:
            invalid_mode_flags.append("--json")
        if args.max_results != MAX_RESULTS:
            invalid_mode_flags.append("--max-results")
        if invalid_mode_flags:
            parser.error(
                "--design-system cannot be combined with "
                + ", ".join(invalid_mode_flags)
                + "."
            )
    else:
        invalid_design_system_flags = []
        if args.persist:
            invalid_design_system_flags.append("--persist")
        if args.page:
            invalid_design_system_flags.append("--page")
        if args.output_dir:
            invalid_design_system_flags.append("--output-dir")
        if args.project_name:
            invalid_design_system_flags.append("--project-name")
        if args.format != "ascii":
            invalid_design_system_flags.append("--format")
        if invalid_design_system_flags:
            parser.error(
                ", ".join(invalid_design_system_flags)
                + " require --design-system."
            )

    if args.page and not args.persist:
        parser.error("--page requires --persist.")
    if args.output_dir and not args.persist:
        parser.error("--output-dir requires --persist.")

    # Design system takes priority
    if args.design_system:
        result = generate_design_system(
            args.query, 
            args.project_name, 
            args.format,
            persist=args.persist,
            page=args.page,
            output_dir=args.output_dir
        )
        print(result)
        
        # Print persistence confirmation
        if args.persist:
            design_system_dir = Path(result["design_system_dir"])
            created_files = [Path(path) for path in result.get("created_files", [])]

            try:
                display_dir = design_system_dir.relative_to(Path.cwd())
            except ValueError:
                display_dir = design_system_dir

            master_file = next(
                (path for path in created_files if path.name == "MASTER.md"),
                design_system_dir / "MASTER.md",
            )
            try:
                display_master_file = master_file.relative_to(Path.cwd())
            except ValueError:
                display_master_file = master_file

            print("\n" + "=" * 60)
            print(f"✅ Design system persisted to {display_dir}/")
            print(f"   📄 {display_master_file} (Global Source of Truth)")
            page_files = [path for path in created_files if path.name != "MASTER.md"]
            if page_files:
                page_file = page_files[0]
                try:
                    display_page_file = page_file.relative_to(Path.cwd())
                except ValueError:
                    display_page_file = page_file
                print(f"   📄 {display_page_file} (Page Overrides)")
            print("")
            print(f"📖 Usage: When building a page, check {display_dir}/pages/[page].md first.")
            print("   If exists, its rules override MASTER.md. Otherwise, use MASTER.md.")
            print("=" * 60)
    # Stack search
    elif args.stack:
        result = search_stack(args.query, args.stack, args.max_results)
        if args.json:
            import json
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_output(result))
    # Domain search
    else:
        result = search(args.query, args.domain, args.max_results)
        if args.json:
            import json
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_output(result))
