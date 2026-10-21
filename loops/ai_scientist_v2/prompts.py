"""
Every prompt the loop sends, as templates filled in with `str.format`.

Adapted from AI Scientist-v2 (see LICENSE); the comment above each group names the
upstream source. Changes from upstream are listed in this folder's README.
"""

# Our addition: some models, e.g. Opus 5.5, reject a forced tool_choice
CALL_TOOL = "Reply by calling the `{name}` tool."

# Idea: `ai_scientist/perform_ideation_temp_free.py`. The task takes the place of the
# workshop description, and the sandbox limits are added.
IDEA_SYSTEM = (
    "You are an experienced researcher who aims to propose high-impact research "
    "ideas resembling exciting grant proposals. Feel free to propose any novel ideas "
    "or experiments; make sure they are novel. Be very creative and think out of the "
    "box. Each proposal should stem from a simple and elegant question, observation "
    "or hypothesis about the topic. For example, they could involve very interesting "
    "and simple interventions or investigations that explore new possibilities or "
    "challenge existing assumptions. Clearly explain how the proposal differs from "
    "the existing literature.\n\n"
    "The experiments must be computational and run on a CPU within {timeout} "
    "seconds each, with no internet access, using numpy, pandas, scikit-learn, "
    "scipy and matplotlib, and only synthetic data or datasets bundled with those "
    "packages.\n\n"
    "Use `search_papers` to search the literature, and `finalize_idea` when the "
    "idea is ready. Search at least once before finalising, so the idea is "
    "well-informed by existing research."
)

IDEA_TASK = (
    "{prompt}\n\n"
    "Propose a research idea for this task. If it already includes research "
    "questions or a literature review, build on them rather than redoing them."
)

IDEA_REFLECTION = (
    "Round {round}/{rounds}.\n\n"
    "In your thoughts, first carefully consider the quality, novelty and feasibility "
    "of the proposal so far, and any other factors you think are important. Keep it "
    "clear and concise, and don't make things overly complicated. Then refine and "
    "improve the proposal, sticking to the spirit of the original idea unless there "
    "are glaring issues. Incorporate any new results from your searches."
)

# Search stages: `ai_scientist/treesearch/agent_manager.py` (`main_stage_goals`),
# generalised from training ML models to any computational research, with data
# offline. In stage order.
STAGE_GOALS = {
    "initial_implementation": (
        "- Get a basic, working first version of the experiment, analysis or "
        "simulation\n"
        "- Keep it simple: one dataset, model or setting\n"
        "- Aim for correctness before anything else"
    ),
    "baseline_tuning": (
        "- Refine the settings of the current approach so its results are better or "
        "more reliable, e.g. sample sizes, iterations, parameters, thresholds or "
        "preprocessing choices\n"
        "- DO NOT change the approach itself from the previous stage\n"
        "- Where it makes sense, check that the results hold on other data or settings"
    ),
    "creative_research": (
        "- Explore novel improvements or extensions of the approach\n"
        "- Come up with experiments or analyses that reveal new insights\n"
        "- Be creative and think outside the box"
    ),
    "ablation_studies": (
        "- Find out which parts of the approach matter: remove or vary one component, "
        "assumption or choice at a time and measure its effect on the results\n"
        "- Keep the data and everything else as in the previous stage"
    ),
}

# Operators: `ai_scientist/treesearch/parallel_agent.py`, without the GPU, PyTorch
# and HuggingFace requirements, generalised beyond ML, and with our `metrics.json`
# contract. Each operator's prompt is a list of sections; see `operators.py`.
RESEARCH_IDEA = (
    "You are an ambitious researcher who is looking to publish a paper that "
    "will contribute significantly to the field. You have an idea and you "
    "want to carry out computational experiments or analyses to gain "
    "scientific insights.\n\n"
    "Title: {title}\n"
    "Abstract: {abstract}\n"
    "Short Hypothesis: {hypothesis}\n"
    "Experiments: {experiments}"
)

IMPLEMENTATION_GUIDELINE = (
    "- The code must be a single, self-contained Python script that runs "
    "as-is from top to bottom. Don't put code in an "
    "`if __name__ == '__main__':` block, and don't skip any parts.\n"
    "- It runs on CPU only, with no internet access: nothing can be "
    "downloaded or installed.\n"
    "- Available packages: numpy, pandas, scikit-learn, scipy and "
    "matplotlib.\n"
    "- Use only data the script can create or that is already installed: "
    "simulated or synthetic data, or datasets bundled with installed "
    "packages (e.g. scikit-learn's `load_*` datasets). Don't use functions "
    "that download data, such as scikit-learn's `fetch_*`.\n"
    "- It must finish within {timeout} seconds.\n"
    "- The script runs in its own empty folder. Write all files there.\n"
    "- Print the results, including `{metric}`.\n"
    "- At the end, write `metrics.json` with the metric as a top-level "
    'number: `{{"{metric}": value}}`. If the script runs several settings, '
    "use the value for the main one; other results can go under other "
    "keys.\n"
    "- Save plots as PNG files with distinct, descriptive names."
)

DRAFT_INTRO = (
    "Your first task is to write Python code for a solid first version of "
    "the experiment or analysis in your research idea, from preparing the "
    "data to computing and visualising the results. Focus on getting a "
    "simple but working implementation "
    "first, before any sophisticated improvements. We will explore more "
    "advanced variations in later stages."
)

DRAFT_GUIDELINE = (
    "- This first design should be relatively simple, without extensive "
    "tuning of its settings.\n"
    "- Take the Memory section into consideration.\n"
    "- The plan should be 6-10 sentences.\n"
    "- Don't suggest exploratory data analysis.\n"
    "- Create synthetic data if needed."
)

DEBUG_INTRO = (
    "You are an experienced researcher. Your previous code for the "
    "research experiment had a bug, so based on the information below, you "
    "should revise it in order to fix this bug."
)

DEBUG_GUIDELINE = (
    "- The plan should be 3-5 sentences on how to fix the issue.\n"
    "- Don't suggest exploratory data analysis.\n"
    "- Submit the complete code, including the parts that didn't change."
)

IMPROVE_INTRO = (
    "You are an experienced researcher. You are provided with a previously "
    "developed implementation. Your task is to improve it based on the "
    "current experimental stage."
)

IMPROVE_GUIDELINE = (
    "- The plan should be 7-10 sentences.\n"
    "- Submit the complete code, including the parts that didn't change."
)

TUNE_INTRO = (
    "You are a researcher refining the settings of a first experiment or "
    "analysis. Based on the current implementation and previous attempts, "
    "propose and implement ONE change to a setting, such as a sample size, "
    "number of iterations, parameter, threshold or preprocessing choice, to "
    "see if it makes the results better or more reliable. Start with the "
    "settings most likely to matter."
)

TUNE_REQUIREMENTS = (
    "- Change ONE specific setting, different from previous attempts.\n"
    "- The plan should be 3-5 sentences on what is changed and why.\n"
    "- Submit the complete code, including the parts that didn't change."
)

ABLATE_INTRO = (
    "You are a researcher finding out which parts of your approach matter, "
    "with an ablation or sensitivity study. Based on the current "
    "implementation and previous ablations, propose and implement ONE new "
    "ablation that removes or varies a different component, assumption or "
    "choice."
)

ABLATE_REQUIREMENTS = (
    "- Ablate ONE specific component, assumption or choice.\n"
    "- It must be a new idea, not a variation of previous ablations.\n"
    "- If only one dataset or setting has been used so far, one ablation "
    "should use several (at least 3) different ones.\n"
    "- The plan should be 3-5 sentences on what is ablated and why.\n"
    "- Submit the complete code, including the parts that didn't change."
)

# Node review: `ai_scientist/treesearch/parallel_agent.py` (`parse_exec_result`,
# `_analyze_plots_with_vlm`). The bug definition and the metric read are ours.
REVIEW_OUTPUT = (
    "You are an experienced researcher. You have written code for your "
    "research experiment and now need to evaluate the output of the code "
    "execution. Analyse the execution output, determine if there were any bugs, "
    "and provide a summary of the findings.\n\n"
    "A bug is code that fails to do what it intends: an error, a wrong "
    "calculation or missing outputs. A surprising, null or unusually stable "
    "result is a finding, not a bug, if the code is correct.\n\n"
    "Research idea:\n{idea}\n\n"
    "Implementation:\n```python\n{code}\n```\n\n"
    "Execution output:\n```\n{output}\n```\n\n"
    "`{metric}` read from `metrics.json`: {value} (None means it is "
    "missing or not a number, which is a bug)"
)

REVIEW_PLOTS = (
    "You are an experienced researcher analysing experimental results. You "
    "have been provided with plots from an experiment.\n\n"
    "Research idea:\n{idea}"
)

# Best node and stage completion: `ai_scientist/treesearch/agent_manager.py` and
# `journal.py` (`get_best_node`)
SELECT_BEST = (
    "You are an experienced researcher evaluating different implementations of "
    "an experiment to select the best one. You should consider all aspects, "
    "including the metric, the review of each run's output and the feedback on "
    "its plots.\n\n"
    "Select the best implementation from the candidates below, considering all "
    "available evidence. The metric is `{metric}`, and {direction} is "
    "better, but avoid relying too heavily on it alone, because it may not be "
    "directly comparable across implementations.\n\n"
    "Candidates:\n{candidates}"
)

TUNING_DONE = (
    "Evaluate if the baseline tuning stage is complete, based on the following "
    "evidence from its best implementation.\n\n"
    "Plan: {plan}\n"
    "Metric: {metric}\n"
    "Review: {summary}\n"
    "Plot feedback: {plot_feedback}\n\n"
    "The stage's goals:\n{goals}\n\n"
    "Requirements for completion:\n"
    "1. The results should be stable and reliable\n"
    "2. Where it makes sense, they should hold on more than one dataset or "
    "setting\n"
    "3. No major instabilities or issues in the plots"
)

# Literature review and analysis: ours; upstream has no separate stage outputs
LIT_REVIEW_SYSTEM = "You are an experienced researcher writing a literature review."

LIT_REVIEW = (
    "Task:\n{prompt}\n\n"
    "Research idea: {title}\n{hypothesis}\n\n"
    "Related work, as summarised in the idea:\n{related_work}\n\n"
    "Papers:\n{papers}\n\n"
    "Write a short markdown literature review of these papers. Group them by "
    "theme, say how each relates to the idea, and name the gap the idea "
    "addresses. Cite papers only by their number, e.g. [3]. Don't add a "
    "references section; it is added for you."
)

ANALYSIS_SYSTEM = (
    "You are an experienced researcher analysing your experiments' results."
)

ANALYSIS = (
    "Research idea:\n{idea}\n\n"
    "The metric is `{metric}`, and {direction} is better.\n\n"
    "Best implementation of each search stage:\n{bests}\n\n"
    "Ablations, against {metric} = {base} before ablating:\n{ablations}\n\n"
    "Recent attempts:\n{journal}\n\n"
    "Write a markdown analysis of what the results show about the hypothesis, "
    "which ablated parts mattered, and how far the results can be trusted. "
    "Quote numbers only from the metrics given."
)

# Citations and report: `ai_scientist/perform_icbinb_writeup.py`
# (`get_citation_addition`, `writeup_system_message_template`), for a markdown
# report instead of LaTeX
CITATION_SYSTEM = (
    "You are an ambitious researcher who has completed your experiments and is now "
    "collecting citations to related papers, to be used in the report.\n\n"
    "Reasons to reference papers include:\n"
    "1. Summarising research: when summarising the existing literature.\n"
    "2. Using specific concepts: when discussing specific theories or concepts.\n"
    "3. Datasets, models and methods: cite their creators.\n"
    "4. Comparing findings: when comparing or contrasting different findings.\n"
    "5. Highlighting research gaps: when pointing out gaps your study addresses.\n"
    "6. Using established methods: cite the creators of methods you use.\n"
    "7. Supporting arguments: sources that back up your conclusions.\n"
    "8. Suggesting future research: studies related to future directions.\n\n"
    "Collect citations for all of these categories. Aim for a broad range of "
    "relevant papers, not just the most popular ones. You have {rounds} rounds, but "
    "do not need to use them all. DO NOT ADD A CITATION THAT ALREADY EXISTS!"
)

CITATION_CONTEXT = (
    "Round {round}/{rounds}.\n\n"
    "Your idea:\n{idea}\n\n"
    "Your analysis of the results:\n{analysis}\n\n"
    "Your current citations:\n{citations}"
)

FIND_CITATION = (
    "{context}\n\nIdentify the most important citation you still need to "
    "add, and the query to find it, or say you are done."
)

SELECT_CITATIONS = (
    "{context}\n\nYou are looking for: {description}\n\n"
    "Search found:\n{papers}\n\nSelect the papers that best fit, if any. "
    "Don't select papers that are already cited."
)

REPORT_SYSTEM = (
    "You are an ambitious researcher writing up your project as a report. You must "
    "accurately represent the results of the experiments: negative, unexpected or "
    "inconclusive findings are valid contributions. Write markdown with these "
    "sections:\n\n"
    "- **Title**: catchy and informative.\n"
    "- **Abstract**: one paragraph summarising the question, method and findings.\n"
    "- **Introduction**: the problem, why it matters, and the contributions.\n"
    "- **Related Work**: relevant papers, compared and contrasted with this work. "
    "It should have several citations.\n"
    "- **Method**: what was done, in enough detail to repeat it.\n"
    "- **Results**: what the experiments found.\n"
    "- **Ablations**: which parts of the approach mattered.\n"
    "- **Limitations**: how far the results can be trusted.\n"
    "- **Conclusion**: the main lessons, and next steps.\n\n"
    "Don't invent results or citations. Don't add a references section; it is "
    "added for you."
)

REPORT = (
    "Write up the following idea:\n{idea}\n\n"
    "Your analysis of the results:\n{analysis}\n\n"
    "Best implementation of each search stage:\n{bests}\n\n"
    "Papers you can cite:\n{citations}\n\n"
    "Quote numbers only from the metrics given, and cite papers only by their "
    "number, e.g. [3]."
)
