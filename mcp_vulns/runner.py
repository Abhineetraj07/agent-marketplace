"""
MCP Vulnerability Demo Runner

Demonstrates 5 MCP-specific attacks and the marketplace's active defenses.

Usage:
    python -m mcp_vulns.runner --all                    # Run all 5 demos
    python -m mcp_vulns.runner --vuln 2                 # Run only tool poisoning
    python -m mcp_vulns.runner --vuln 1 3 5             # Run specific vulns
    python -m mcp_vulns.runner --all --defense-only     # Show only defense results
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_vulns.vuln1_supply_chain import print_demo as demo1
from mcp_vulns.vuln2_tool_poisoning import print_demo as demo2
from mcp_vulns.vuln3_tool_shadowing import print_demo as demo3
from mcp_vulns.vuln4_rug_pull import print_demo as demo4
from mcp_vulns.vuln5_sandbox_escape import print_demo as demo5

DEMOS = {
    1: ("Supply-Chain Attack", demo1),
    2: ("Tool Poisoning", demo2),
    3: ("Tool Shadowing", demo3),
    4: ("Rug Pull Attack", demo4),
    5: ("Sandbox Escape / RAC", demo5),
}


def main():
    parser = argparse.ArgumentParser(description="MCP Vulnerability Demo Runner")
    parser.add_argument("--all", action="store_true", help="Run all 5 vulnerability demos")
    parser.add_argument("--vuln", type=int, nargs="+", help="Run specific vulnerability demos (1-5)")
    parser.add_argument("--defense-only", action="store_true", help="Show only defense results")
    args = parser.parse_args()

    if not args.all and not args.vuln:
        parser.print_help()
        sys.exit(1)

    vulns = list(DEMOS.keys()) if args.all else (args.vuln or [])

    print("\n" + "#" * 60)
    print("#" + " " * 58 + "#")
    print("#    MCP VULNERABILITY DEFENSE DEMONSTRATION" + " " * 15 + "#")
    print("#    Agent Marketplace Security Suite" + " " * 22 + "#")
    print("#" + " " * 58 + "#")
    print("#" * 60)

    passed = 0
    failed = 0

    for v in vulns:
        if v not in DEMOS:
            print(f"\nUnknown vulnerability: {v}. Valid: 1-5")
            continue

        name, demo_fn = DEMOS[v]
        try:
            results = demo_fn(defense_only=args.defense_only)

            # Check if defense worked
            defense_worked = False
            if v == 1:
                defense_worked = results.get("defense", {}).get("blocked", False)
            elif v == 2:
                defense_worked = all(d.get("blocked", False) for d in results.get("defense", []))
            elif v == 3:
                defense_worked = results.get("defense", {}).get("shadowing_detected", False)
            elif v == 4:
                defense_worked = results.get("defense", {}).get("blocked", False)
            elif v == 5:
                defense_worked = (
                    results.get("static_analysis", {}).get("blocked", False)
                    and results.get("runtime_sandbox", {}).get("all_attacks_blocked", False)
                )

            if defense_worked:
                passed += 1
            else:
                failed += 1

        except Exception as e:
            print(f"\nError running vuln {v} ({name}): {e}")
            failed += 1

    # Summary
    total = passed + failed
    print("\n" + "#" * 60)
    print(f"#  RESULTS: {passed}/{total} defenses active" + " " * (60 - 25 - len(str(passed)) - len(str(total))) + "#")
    if failed == 0:
        print("#  All MCP attacks blocked successfully!" + " " * 20 + "#")
    else:
        print(f"#  WARNING: {failed} defense(s) need attention" + " " * (60 - 42 - len(str(failed))) + "#")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
