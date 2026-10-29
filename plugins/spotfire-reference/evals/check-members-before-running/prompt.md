---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill, Write]
---
I'm writing an IronPython script for Spotfire Analyst 15.0. It creates a document property, then
sets the property's description, then sets the X axis expression of a line chart on the active
page. Last time a script like this failed half way on a member that didn't exist.

How can I check, against my own Analyst install, that every member I use exists and can be set
before I run the script? Give me the exact steps and commands. My Analyst is installed in
`%LOCALAPPDATA%\Spotfire\15.0.0` and my workspace folder is set in `DXP_WORKSPACE`.
