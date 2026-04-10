"""
FilmBot A2A Client — Sends benchmark questions to the A2A server and collects metrics.
"""

import asyncio
import time
from uuid import uuid4

import httpx

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    Message,
    MessageSendParams,
    SendMessageRequest,
    TextPart,
    Role,
    Task,
)

from filmbot_agent import BENCHMARK_QUESTIONS, get_ground_truth, check_accuracy

SERVER_URL = "http://localhost:9999"


def _get_text_from_part(part) -> str | None:
    """Extract text from a Part (which is a root model wrapping TextPart, etc.)."""
    inner = part.root if hasattr(part, "root") else part
    if hasattr(inner, "text"):
        return inner.text
    return None


def _extract_response_text(response) -> str:
    """Extract text from a SendMessageResponse."""
    result = response.root
    # result is either JSONRPCErrorResponse or SendMessageSuccessResponse
    if hasattr(result, "result"):
        inner = result.result
        # inner is either Task or Message
        if isinstance(inner, Task):
            if inner.artifacts:
                for artifact in inner.artifacts:
                    for part in artifact.parts:
                        text = _get_text_from_part(part)
                        if text:
                            return text
            if inner.history:
                for msg in reversed(inner.history):
                    if msg.role == Role.agent:
                        for part in msg.parts:
                            text = _get_text_from_part(part)
                            if text:
                                return text
            if inner.status and inner.status.message:
                for part in inner.status.message.parts:
                    text = _get_text_from_part(part)
                    if text:
                        return text
            return "No response text found in task"
        else:
            # It's a Message
            for part in inner.parts:
                text = _get_text_from_part(part)
                if text:
                    return text
            return "No text parts in message"

    if hasattr(result, "error"):
        return f"Error: {result.error.message}"
    return "Unknown response format"


async def run_a2a_benchmark(api_key: str, questions: list[str] = None, ground_truth: dict = None):
    """Send benchmark questions via A2A and collect results."""
    if questions is None:
        questions = BENCHMARK_QUESTIONS
    if ground_truth is None:
        ground_truth = get_ground_truth()

    results = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as discovery_client:
        resolver = A2ACardResolver(httpx_client=discovery_client, base_url=SERVER_URL)
        card = await resolver.get_agent_card()
        print(f"Connected to: {card.name} v{card.version}")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(300.0),
        headers={"Authorization": f"Bearer {api_key}"},
    ) as httpx_client:
        client = A2AClient(httpx_client=httpx_client, url=card.url)

        for i, question in enumerate(questions, 1):
            print(f"  [{i}/{len(questions)}] {question[:50]}...")

            message = Message(
                role=Role.user,
                parts=[TextPart(text=question)],
                message_id=uuid4().hex,
            )

            request = SendMessageRequest(
                id=str(i),
                params=MessageSendParams(message=message),
            )

            start = time.time()
            try:
                response = await client.send_message(request)
                latency = time.time() - start

                response_text = _extract_response_text(response)
                is_accurate, details = check_accuracy(question, response_text, ground_truth)

                status_icon = "+" if is_accurate else "x"
                print(f"    {status_icon} Latency: {latency:.2f}s | {details}")

                results.append({
                    "question_id": i,
                    "question": question,
                    "response": response_text[:500],
                    "latency": round(latency, 2),
                    "is_accurate": is_accurate,
                    "accuracy_details": details,
                    "status": "SUCCESS",
                })

            except Exception as e:
                latency = time.time() - start
                print(f"    x ERROR: {e}")
                results.append({
                    "question_id": i,
                    "question": question,
                    "response": f"ERROR: {e}",
                    "latency": round(latency, 2),
                    "is_accurate": False,
                    "accuracy_details": f"Error: {str(e)[:100]}",
                    "status": "ERROR",
                })

    return results


async def main():
    import os
    api_key = os.environ.get("FILMBOT_A2A_API_KEY", "")
    if not api_key:
        print("Set FILMBOT_A2A_API_KEY env var to the server's API key.")
        return

    ground_truth = get_ground_truth()
    results = await run_a2a_benchmark(api_key, BENCHMARK_QUESTIONS, ground_truth)

    print(f"\nCompleted: {sum(1 for r in results if r['status'] == 'SUCCESS')}/{len(results)} successful")
    print(f"Accurate: {sum(1 for r in results if r['is_accurate'])}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
