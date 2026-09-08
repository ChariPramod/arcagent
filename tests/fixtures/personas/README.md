# Fixture personas

These exist to test the harness, not the agent. They are deliberately kept out of
`evals/personas/`, which is owner authored: if the agent wrote personas into the real
directory, the eval would be measuring a model against itself and the numbers would mean
nothing.

Nothing here is ever loaded by `evals.run_text`.
