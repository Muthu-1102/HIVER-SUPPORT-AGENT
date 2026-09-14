"""Interactive and CLI demonstration tool for SpotifySupportAgent.

Usage:
    python scripts/demo_agent.py "Why was I charged twice this month?"
    python scripts/demo_agent.py --interactive
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.spotify_agent.agent import AgentResult, SpotifySupportAgent


def format_agent_result(result: AgentResult, original_input: str) -> str:
    """Format an AgentResult into a clean, human-readable terminal report."""
    cls = result.classification
    sec_intents = ", ".join(cls.secondary_intents) if cls.secondary_intents else "None"
    flags = ", ".join(cls.cross_cutting_flags) if cls.cross_cutting_flags else "None"
    scope = cls.technical_malfunction_scope or "N/A"
    primary = cls.primary_intent or (f"Non-Intent ({cls.non_intent_class})" if cls.is_non_intent else "None")

    lines = [
        "=" * 70,
        "SPOTIFY SUPPORT AGENT - INFERENCE RESULT",
        "=" * 70,
        f"Customer Message:        {original_input.strip()}",
        "-" * 70,
        "CLASSIFICATION:",
        f"  Primary Intent:        {primary}",
        f"  Secondary Intents:     {sec_intents}",
        f"  Technical Scope:       {scope}",
        f"  Cross-Cutting Flags:   {flags}",
        f"  Is Non-Intent:         {cls.is_non_intent}",
        f"  Confidence:            {cls.confidence:.2%}",
        "-" * 70,
        "ROUTING & OPERATIONAL ACTION:",
        f"  Target Queue:          {result.target_queue}",
        f"  Action:                {result.action}",
        f"  Priority:              {result.routing.priority}",
        f"  Human Escalation:      {result.requires_human_escalation}",
        f"  Channel Handoff:       {result.requires_channel_handoff}",
        "-" * 70,
        "GENERATED CUSTOMER-FACING RESPONSE:",
        f"  {result.text}",
        "=" * 70,
    ]
    return "\n".join(lines)


def run_demo(message: str, agent: SpotifySupportAgent | None = None) -> AgentResult:
    """Run agent on single message and print formatted report."""
    if agent is None:
        agent = SpotifySupportAgent()

    result = agent.process_message(message)
    print(format_agent_result(result, message))
    return result


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Demonstrate SpotifySupportAgent intent classification, routing, and response generation."
    )
    parser.add_argument(
        "message",
        nargs="?",
        default=None,
        help="Customer support inquiry text (e.g., 'Why was I charged twice this month?')",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Run in interactive prompt loop mode.",
    )

    args = parser.parse_args()
    agent = SpotifySupportAgent()

    if args.interactive:
        print("=" * 70)
        print("Spotify Support Agent - Interactive Demonstration")
        print("Type your message and press Enter (or type 'quit' / 'exit' to exit)")
        print("=" * 70)
        while True:
            try:
                user_msg = input("\nCustomer Inquiry > ").strip()
                if not user_msg:
                    continue
                if user_msg.lower() in ("quit", "exit", "q"):
                    print("Exiting demonstration.")
                    break
                run_demo(user_msg, agent)
            except (KeyboardInterrupt, EOFError):
                print("\nExiting demonstration.")
                break
    elif args.message:
        run_demo(args.message, agent)
    else:
        # Default sample execution
        sample_msg = "Why was I charged twice for Spotify Premium this month?"
        print("No message provided. Running with sample inquiry:")
        run_demo(sample_msg, agent)


if __name__ == "__main__":
    main()
