# 🤖 Universal AI Agent Protocol

This file defines how *any* AI service (Claude, Gemini, Codex, etc.) must behave in this repository to ensure a seamless handoff between different agents.

## 🏁 1. Startup Phase (Mandatory)
Before doing *anything* else, you MUST:
1.  **Read `memory/MEMORY.md`**: Look at the `Latest Context (Handoff Note)` section. 
2.  **Adopt the Context**: Immediately pick up where the last agent left off. Do not ask the user for "what happened" if it is in the handoff note.
3.  **Check Sync Status**: Verify in the `Session Sync` table that no other agent is currently "In Progress" on your specific task.

## ⚙️ 2. Execution Phase
1.  **Update Status**: If you are starting a task that will take multiple turns, update your status in `memory/MEMORY.md` to "In Progress".
2.  **Log Ideas**: If you find a bug or have an improvement idea, add it to `memory/ideas_and_improvements.md` immediately.
3.  **Consult the Master**: Use `AGENTS.md` as your primary source for architecture, commands, and technical constraints.

## 🏁 3. Completion Phase (The Handoff)
Before you finish your session, you MUST:
1.  **Update the Handoff Note**: Edit `memory/MEMORY.md` -> `Latest Context (Handoff Note)`.
    *   Summarize what you *actually* finished.
    *   State exactly what the *next step* should be for the next agent.
2.  **Mark Idle**: Set your status to "Idle / Standby" in the sync table.

---
**Core Mandate:** Your goal is to make it so the user never has to repeat themselves. The memory files are your brain; keep them updated.
