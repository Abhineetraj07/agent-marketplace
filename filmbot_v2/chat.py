"""FilmBot V2 — Interactive terminal chat with guardrails."""

from agent import invoke_agent


def main():
    print("=" * 60)
    print("  FilmBot V2 — SQL + Vector Search + Knowledge Graph")
    print("  Guardrails: Active")
    print("  Type 'quit' to exit")
    print("=" * 60)

    while True:
        question = input("\nYou: ").strip()
        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        result = invoke_agent(question)

        if result.get("guardrail_blocked"):
            print(f"\n[BLOCKED — {result['guardrail_category']}]")
            print(f"FilmBot: {result['response']}")
        else:
            print(f"\nFilmBot: {result['response']}")
            print(f"\n  [Tools: {', '.join(result['tools_used']) or 'none'} | "
                  f"Latency: {result['latency']}s | "
                  f"Tool calls: {result['tool_calls']}]")


if __name__ == "__main__":
    main()
