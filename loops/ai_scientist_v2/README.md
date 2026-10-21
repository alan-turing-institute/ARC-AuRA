# AI Scientist-v2 loop

A compact reimplementation of the agentic tree search from *The AI Scientist-v2*
([arXiv 2504.08066](https://arxiv.org/abs/2504.08066); code
`SakanaAI/AI-Scientist-v2@96bd516`), run as aura's `ai-scientist-v2` harness.

Upstream can't run in aura's sandbox: it calls Claude through AWS Bedrock, its prompts
expect a GPU, PyTorch and HuggingFace downloads, and its write-up needs LaTeX. This
version keeps the design (operators, selection policy, stages, a model judge and plot
feedback) and changes what the sandbox or aura's stage outputs require.

## How it works

Unlike Claude Code or OpenCode, the model never runs a long conversation. Each attempt
at the experiment is a **node**: one complete script, written in one model call. The
loop runs it, has the model review it, and stores it in a tree. The loop, not the
model, decides what to try next.

1. **Idea** (`idea.py`): turns the task into one idea. Over up to 5 rounds, the model
   searches the literature through litmcp, then calls `finalize_idea` with a title,
   hypothesis, related work, abstract, experiments, risks, a **metric** (name and
   direction) and the **papers** it relies on.
2. **Tree search** (`search.py`), in four stages, each starting from the previous
   stage's best node:

   | Stage | Operator | Ends when | Node cap |
   |---|---|---|---|
   | `initial_implementation` | draft (up to 3), then improve | a node works | 6 |
   | `baseline_tuning` | tune one setting | a node beats the start node and the model says it's done | 3 |
   | `creative_research` | improve | the cap | 3 |
   | `ablation_studies` | ablate one component | the cap | 4 |

   Each step:
   - **Select** (`select_node`): with probability 0.5, debug a buggy leaf (at most 3
     debugs in a row). Otherwise, improve the best node, or tune or ablate the
     stage's start node.
   - **Write** (`operators.py`): the operator returns a plan and a complete script. Its
     prompt holds the idea, the stage's goals and the sandbox's limits; draft and
     improve also see a summary of the last 10 nodes.
   - **Run and review** (`execute.py`): the script runs in `tree/<id>/` with a
     timeout and must write `metrics.json`. The model reviews the output (bug or not,
     and a summary) and its plots. A node is buggy if it crashed, timed out, wrote no
     metric, or the review says so.
   - **Judge** (`best_node`): the model picks the best working node from metrics,
     reviews and plot feedback, falling back to the best metric.
3. **Outputs** (`report.py`): research questions and research design are filled in
   from the idea; the literature review, analysis and report are model-written. The
   report's citations come from up to 5 rounds of litmcp search. Reference lists are
   built by code from litmcp's metadata, so they can't be made up.

The loop runs only the steps the requested `--stages` need:

| Step | Runs for |
|---|---|
| idea | always |
| literature review | `lit_review` |
| tree search | `experiments`, `analysis`, `report` |
| analysis | `analysis`, `report` |
| citations and report | `report` |

**Files:**

| File | Contents |
|---|---|
| `__main__.py` | CLI; runs the steps for the requested stages |
| `idea.py` | the idea step |
| `search.py` | node selection, the best-node judge and the stages |
| `operators.py` | draft, debug, improve, tune and ablate |
| `execute.py` | runs a node's script and reviews its output and plots |
| `report.py` | the stage outputs and citations |
| `nodes.py` | the `Node` record, the journal and `log.txt` events |
| `llm.py` | model calls through the LiteLLM gateway |
| `literature.py` | litmcp's `search_papers` and `get_paper` |
| `prompts.py` | every prompt, as `str.format` templates |
| `tools.py` | every tool schema the model is asked to call |

## Usage

Through aura:

```bash
aura run dataset_similarity --task-tier 3 --harness ai-scientist-v2 \
  --model claude-haiku-4-5 --budget 1
```

The model must support tool calls and images. aura passes the prompt, model and
stages; the other settings use the defaults below, which can be changed in
`__main__.py` without a rebuild, since `loops/` is mounted into each run.

| Flag | Default | Meaning |
|---|---|---|
| `--timeout` | 600 | script timeout, in seconds |
| `--num-reflections` | 5 | most idea rounds before it must be finalised |
| `--num-drafts` | 3 | drafts in `initial_implementation` |
| `--debug-prob` | 0.5 | chance of debugging a buggy leaf |
| `--max-debug-depth` | 3 | most debugs in a row on one branch |
| `--stage-iters` | 6 3 3 4 | node cap per search stage |
| `--num-cite-rounds` | 5 | most citation rounds |

**Outputs**, in the run folder's `workspace/`:

- `results/<stage>.md` for each requested stage, ending with the disclosure the
  licence requires; `results/experiments/` has the main best node's script, metrics
  and plots, and the journal.
- `idea.json`: the idea.
- `tree/`: a folder per node (`runfile.py`, `output.txt`, `metrics.json`, plots),
  `journal.json` (every node) and `best_nodes.json` (each stage's best).
- `log.txt`, in the run folder itself: one JSON event per line: `idea_search`,
  `idea`, `search_error`, `node`, `stage_end`, `output`, `citations` and
  `budget_exceeded`.

When the run's budget is spent, the loop stops and keeps what it has written; the
journal is saved after every node.

## Changes from upstream

| Area | Upstream | Here | Why |
|---|---|---|---|
| Scope | training ML models | any computational research | aura's tasks aren't only ML |
| Sandbox | GPU, PyTorch, HuggingFace datasets | CPU; numpy, pandas, scikit-learn, scipy, matplotlib; offline data | the sandbox |
| Ideas | several per workshop description | one, from the task | aura runs one task |
| Literature | Semantic Scholar | litmcp, plus abstracts of the idea's papers | aura's literature server |
| Workers | 4 in parallel | one node at a time | simplicity |
| Sub-stages | generated by the model | none | little design value |
| Multi-seed re-runs | 3 seeds after each stage | none | cost |
| Metric | `.npy` files and a model-written parser | `metrics.json`, read by code | simpler, same role |
| Code replies | parsed from markdown | `submit_code` and `submit_change` tool calls | no parsing failures |
| Tune and ablate | a separate call proposes each change | proposed with the code | cost |
| Models | one for code, another for judging | the run's model for everything | a run key allows one model |
| Budget | 62 nodes, 1 h timeout | 16 nodes, 10 min | a $2–5 run |
| Outputs | a LaTeX paper and a reviewer | aura's six stage outputs, markdown, no reviewer | aura compares harnesses on the same outputs |
| Citations | 20 rounds, BibTeX from the model | 5 rounds, references built by code | budget; no made-up references |

**Worth a reviewer's attention:**

- **Prompts** (`prompts.py`, `tools.py`): the comment above each group names its
  upstream source and says what changed. Compare them against upstream for anything
  lost in generalising beyond ML.
- **The bug definition** in `REVIEW_OUTPUT` is ours: a surprising, null or unusually
  stable result counts as a finding, not a bug, and the review sees the metric that
  code read from `metrics.json`.
- **`metrics.json`**: the metric must be a top-level finite number; anything else
  makes the node buggy.
- **Tool calls** (`llm.call_tool`): the loop asks for a tool with a system message
  and `tool_choice="auto"`, since some models (e.g. Opus 5.5) reject a forced choice.
  A reply without the tool call raises an error.
- **Search failures** (e.g. Semantic Scholar's rate limit) go back to the model as
  the tool's result in the idea step, and skip that round in citations.

**Inherited from upstream, worth knowing when reading results:**

- the best-node judge sees the metric, so a weak or saturated metric steers it;
- the model decides when tuning is done, and selection is random, so runs differ;
- the idea step can finalise after one search.

## Licence

Prompts and logic are adapted from upstream, so this folder is a derivative work under
the AI Scientist Source Code License, in `LICENSE`. Every model-written output ends
with a disclosure that an AI system wrote it.
