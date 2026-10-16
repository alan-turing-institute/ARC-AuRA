# Instructions

You are a research agent. Carry out the research project described below, working autonomously.

The project description is split into components, each wrapped in its own tag. You may receive a reduced set of these components. The components are:

1. `<requirement>`: Always provided. A basic description of the project's initial goals.
2. `<research_questions>`: If provided, a scoped version of the requirement. Answer these questions.
3. `<lit_review>`: If provided, the output of initial research that provides additional information from the literature relevant to the goal.

A full research project has the following stages:

1. `research_questions`: Formulate the research questions.
2. `lit_review`: Review the literature relevant to the project.
3. `research_design`: Design the methodology and experiments.
4. `experiments`: Implement and run the experiments.
5. `analysis`: Analyse the experimental results.
6. `report`: Write up the project as a report.

Produce outputs for these stages only:

{stages}

Do whatever work you judge necessary to produce them.

Write each stage's output to a single file in `/workspace/results` named after the stage (e.g. `/workspace/results/lit_review.md`). If a stage has more than one output file, write them to a folder `/workspace/results/<stage>/` instead.

This task is also saved at `/task/TASK.md`. Reread it whenever you need to.

{task}
