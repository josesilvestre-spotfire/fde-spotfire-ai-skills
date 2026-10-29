---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

We keep our data function scripts in Git with dxpkit. On my branch I changed
`functions/forecast_decline.py`, but `dxp status` now prints:

```
spotfire ahead  forecast_decline -> ${ANALYSES}/decline_review.dxp
```

The demo is in an hour. Can I just run `dxp push --force` to get my change into the DXP?

Also, our pull requests only ever show "Binary file not shown" for the .dxp files. Set us up so
we can see what changed inside them.

Write your answer to `answer.md`, and write the `.gitattributes` file and any commands we need.
