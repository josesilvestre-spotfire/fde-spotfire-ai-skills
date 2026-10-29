# AI usage policy

- The skills in this library were written with Claude Code and reviewed by a person before each
  release.
- The skills instruct the agent to keep a person in the loop wherever Spotfire or your process
  requires one: trusting scripts, approving a promotion, accepting changes to an owner's
  calculation logic.
- Engineering content (the domain context plugin) is pending review by subject matter experts.
  Check its numbers against your own references before you rely on them.
- Running the skills sends your prompts and the files the agent reads to the model provider you
  use with your agent. Do not point the skills at data you are not allowed to share with that
  provider.
- `claude plugin eval` runs on your machine with your own credential. Results stay local unless
  you publish the report.
