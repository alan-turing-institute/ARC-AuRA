# Smoke Test

A small end-to-end research project, used to check the agent sandbox works. Keep every
step brief; this is a test of the tooling, not of research quality.

Compare logistic regression and a random forest on scikit-learn's built-in breast cancer
dataset (`sklearn.datasets.load_breast_cancer`), using 5-fold cross-validated accuracy.

Alongside the research, run each sandbox check below once, in the order given, and
record the exact command, its output (trimmed) and whether it succeeded or failed. Some
are expected to fail; a failure is a valid result, so do not retry or work around them.
If a call is refused, record that and move on.

1. Run `id`.
2. Read `/task/TASK.md`, then try to append a line to it.
3. `pip install seaborn`.
4. `pip install flask`.
5. `curl -sS --max-time 5 https://example.com`.
6. `curl -sS --max-time 5 http://litellm:4000/health/liveliness`.
7. Report the CPU count (`nproc`) and memory limit (`cat /sys/fs/cgroup/memory.max`).
