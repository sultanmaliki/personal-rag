"""One-off evaluation script: 10 per-repo specific questions + 10 broad
cross-repo questions against the live pipeline. Prints results as it goes
and writes a markdown report to eval_results.md at the project root.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import pipeline  # noqa: E402

PER_REPO_QUESTIONS = [
    ("portfolio", "What is the Syed Mohammed Sultan portfolio project built with, and what's its design focus?"),
    ("Custom-Language-Translator", "What language does the Custom-Language-Translator project translate, and how was the model trained?"),
    ("QueryCraft-AI", "What does QueryCraft-AI do and what tech stack is it built on?"),
    ("syedmohammedsultan-online-subdomains", "What does the syedmohammedsultan-online-subdomains project do and how does it sync its data?"),
    ("Project-Management-Web-App", "What features does the Project-Management-Web-App (ProjectFlow) have?"),
    ("LinkedOut", "What is LinkedOut and what problem does it solve?"),
    ("setbeat", "What is SetBeat and what platform is it for?"),
    ("sultanmaliki", "What is in the sultanmaliki repo?"),
    ("hospital-management-system", "What does the hospital-management-system do and what tech does it use?"),
    ("personal-rag", "What is the personal-rag project and what does it do?"),
]

BROAD_QUESTIONS = [
    "What all do you know?",
    "What projects have you built?",
    "List all my projects.",
    "How many projects do you know about?",
    "What programming languages do I use across my projects?",
    "Which of my projects use AI or machine learning?",
    "What is the most complex project you know about?",
    "Summarize my work as a developer.",
    "Which of my projects use a database?",
    "Tell me about your knowledge base.",
]


def run(label: str, question: str, report: list[str]) -> None:
    print(f"\n=== [{label}] {question}")
    t0 = time.time()
    answer = pipeline.answer_question(question)
    dt = time.time() - t0
    print(f"--- {dt:.1f}s, {len(answer.sources)} sources")
    print(answer.text)

    report.append(f"### [{label}] {question}\n")
    report.append(f"**Latency:** {dt:.1f}s | **Sources:** {len(answer.sources)}\n\n")
    report.append(f"**Answer:**\n\n{answer.text}\n\n")
    if answer.sources:
        report.append("**Cited sources:**\n")
        for s in answer.sources:
            report.append(f"- {s.label}\n")
    report.append("\n---\n\n")


def main() -> None:
    report: list[str] = ["# Live Evaluation Run\n\n"]

    report.append("## Part 1: Per-repo specific questions (10)\n\n")
    for repo, q in PER_REPO_QUESTIONS:
        run(repo, q, report)

    report.append("## Part 2: Broad cross-repo questions (10)\n\n")
    for q in BROAD_QUESTIONS:
        run("broad", q, report)

    out_path = Path(__file__).resolve().parent.parent / "eval_results.md"
    out_path.write_text("".join(report), encoding="utf-8")
    print(f"\n\nWrote report to {out_path}")


if __name__ == "__main__":
    main()
