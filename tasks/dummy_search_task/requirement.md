# Dummy Search Task

This task tests your file search tools. Use your built-in glob and grep tools for both
steps, not shell commands such as `find`, `ls` or `grep`.

Search scikit-learn's installed source in
`/usr/local/lib/python3.12/site-packages/sklearn/cluster`:

1. With the glob tool, list the `.py` files directly in that folder (not subfolders).
2. With the grep tool, find every file in that folder or its subfolders that defines a class
   inheriting directly from `ClusterMixin`.

Write both lists, and the number of files in each, to `results/search.md`.
