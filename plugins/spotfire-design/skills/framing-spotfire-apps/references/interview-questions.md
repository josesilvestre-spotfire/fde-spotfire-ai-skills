# Interview questions for the app owner

Ask in this order, three to five questions per round. Start with the business problem and do not
discuss pages or visuals until the owner agrees with your summary of it. Each group fills one
section of the App Brief.

When an answer is vague, use the follow-up in the last column before you move on.

## 1. Business problem

| Question | Follow-up when the answer is vague |
|---|---|
| What goes wrong today that this analysis should help with? | "Can you describe the last time it happened?" |
| Who has this problem? Which roles, which sites or teams? | "Who notices first? Who pays for it?" |
| What does it cost when it happens? | "In hours, money, lost production, downtime, risk? Per event or per month?" |
| How often does it happen? | "How many times last year?" |
| How is it handled now? | "Which tools, files or reports? How long does that take each time?" |
| What would a good outcome look like in six months? | "Which number would change, and by how much?" |
| Is this one problem, or several that share data? | "If we built only one of them first, which one?" |

## 2. Users

| Question | Follow-up |
|---|---|
| Who will open the analysis, and what is their job? | "Engineer, analyst, planner, supervisor, manager?" |
| How often does each of them use it? | "Daily, weekly, during an event, once a quarter?" |
| Where do they open it? | "Spotfire Analyst, Web Player, or both? On a plant network without internet?" |
| Will they run it on their own data or only look at results? | "Who loads new data, and from where?" |
| What do they know already? | "Do they know the method, or do they need it explained on a page?" |

## 3. Decisions

| Question | Follow-up |
|---|---|
| Which decisions should this analysis help each user make? | "What do they do differently after looking at it?" |
| What must they see to make that decision? | "Which number, trend, comparison or map?" |
| At what value do they act? | "Is there a limit, a target or a rule of thumb?" |
| What happens if they decide wrongly? | "Is the cost of acting too early different from acting too late?" |

## 4. KPIs and calculations

| Question | Follow-up |
|---|---|
| Which three to six numbers matter most? | "If the page could show only one number, which one?" |
| How is each one calculated? | "Is there an equation, a standard, a correlation, or an existing spreadsheet?" |
| Which units do the users work in? | "Field units, SI, or mixed? Per day or per hour?" |
| What threshold or target applies to each? | "Who sets it, and does it differ by asset?" |
| Which existing results must the new analysis reproduce? | "Is there a report or workbook we can check our numbers against?" |

## 5. Inputs

| Question | Follow-up |
|---|---|
| What should users be able to change? | "Asset, date range, threshold, price, scenario?" |
| For each input: default value and allowed range? | "What value do they use most often?" |
| Which of these are real operating decisions? | "Could an operator or planner change this in the plant or the business?" |
| Are there settings only an expert should touch? | "Model settings, calibration constants, demo data options?" |

## 6. Outputs

| Question | Follow-up |
|---|---|
| What should users take away from the analysis? | "A chart, a ranked list, a table to export, an alert?" |
| Who receives each output? | "Is it shared by email, in a meeting, or loaded into another system?" |
| Is there a report or format the output must match? | "Can you share an example?" |

## 7. Data sources

| Question | Follow-up |
|---|---|
| Where does the data come from? | "Historian, database, files, an API? Who owns each source?" |
| What is the grain of each source? | "One row per hour per asset? Per well per day? Per event?" |
| How much data? | "How many assets, how many years, how many rows?" |
| What columns must users supply if they bring their own data? | "Which are required and which are nice to have? What do we do when one is missing?" |
| Are there known data problems? | "Gaps, frozen values, unit changes, renamed tags?" |
| Can the data leave its system? | "Is it confidential? Can a sample be embedded in the DXP?" |

## 8. Refresh

| Question | Follow-up |
|---|---|
| How fresh must the data be? | "Is yesterday's data good enough?" |
| Who or what triggers a refresh? | "On open, on a schedule, or when a user presses a button?" |
| How long may a refresh take? | "Seconds, a minute, or run overnight?" |

## 9. Scope and constraints

| Question | Follow-up |
|---|---|
| What should this first release not do? | "What will someone ask for next that we should postpone?" |
| Are there deadlines, reviews or approvals? | "Who signs it off?" |
| Are there IT constraints? | "Offline clients, Python packages allowed, library location?" |

## After the interview

Summarise the business problem back to the owner in two to four sentences, in their words, and ask
them to correct it. Write the brief only after they agree with the summary.
