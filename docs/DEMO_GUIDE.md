# Demo guide (for the video and the live finals)

**Before you start:** deploy with a real LLM and embeddings, `VECTOR_BACKEND=mongodb`, and READY
Vector Search indexes. Sign in as the demo account and click the reset icon (bottom left) for a clean
start. The sidebar must say **MongoDB Vector Search**, not "Local fallback". Keep the Memories page
open in a second tab.

The demo account starts with sample data from an "earlier session": learning NLP, wanting to build AI
agents, and struggling with recursion, linked in the graph (NLP related to Machine Learning).

| # | Do this | Point out |
|---|---|---|
| 1 | New conversation: *"I prefer learning algorithms with visual examples."* | "Updating memory" then "Memory updated". Memories page: a Preference with confidence and evidence. Graph: You, prefers, visual examples, used for, Algorithms. Activity: "Memory created" with its reason. |
| 2 | **New conversation**: *"Explain binary search."* | The answer is visual. Open **Memories used**: the preference, why it was retrieved (core profile), and **Show original messages** to reveal the exact sentence from session 1. Working memory panel: tokens per tier. |
| 3 | *"I no longer want visual explanations. Give me code-first explanations."* then *"Explain quicksort."* | Memories page, Replaced tab: the old preference, linked to its replacement (History). Graph with "Show replaced links": dashed old edge. Quicksort answer is code-first. |
| 4 | *"I prefer short explanations."* then *"For mathematics, I want detailed explanations."* New conversation: *"Explain the chain rule in calculus."* then *"Anyway, new topic: explain merge sort."* | Both memories stay active (different scopes). For calculus, the maths-specific one is used and the short one is listed as **Not applied (overridden)**. The explicit "new topic" starts a new episode (divider in chat); merge sort gets the short answer. |
| 5 | *"I have an exam next Monday."* then *"What should I study today?"* | A temporary Constraint with an expiry date, used in the plan. Click **+7 days** twice: "1 temporary memory expired"; ask again and it is gone. Activity: "Memory expired". Mention the TTL index plus the app-side expiry check. Click **Today** to reset. |
| 6 | *"Forget that I struggle with recursion."* then *"Can you explain recursion?"* | Memories, Forgotten tab: content wiped. Graph: the Recursion node is gone. The answer no longer assumes a difficulty. Activity: "Memory forgotten" (earlier events about it are redacted). |
| + | *"Back to recursion: what did I get wrong last time?"* | The episodic gate fires: the working memory panel shows evidence from a past episode, fetched through message pointers. |

**Talking points:** typed memory documents in MongoDB; Vector Search with user/workspace/status
filters; evidence pointers; supersede, not overwrite; scope-aware conflicts; TTL plus app-side expiry;
forget with tombstones; working memory is a few hundred tokens instead of the whole history
(`scripts/context_report.py <conversation_id>` prints the measured numbers for a conversation).

**If the LLM API fails live:** play the recorded video. Never fake results.
