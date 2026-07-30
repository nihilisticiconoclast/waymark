---
name: changing-course
description: >-
  How to tell that an approach is failing and switch to a different one, instead of tuning a
  broken approach for hours. Use when a fix has not worked more than twice, when the same
  complaint comes back from the user a second time, when each attempt costs a slow round trip
  (CI, a rate-limited API, a deploy), when you are adding parameters to make something
  behave, or when deciding what to report as progress. Read it early — its whole value is
  being consulted before the fourth attempt rather than after the tenth.
---

# Changing course

Persistence and stubbornness look identical from the inside. The difference is whether the
thing is getting better, and that has to be measured rather than felt.

This exists because of a build that spent most of a day on one routing heuristic across six
slow CI rounds, produced a worse result each time, and was then replaced in twenty minutes by
a simpler algorithm that worked immediately. Every signal below was present by round two.

---

## Signals the approach is wrong, not underfit

**Each fix produces a different wrong answer rather than a closer one.** This is the clearest
signal and the easiest to miss, because every individual fix is a genuine improvement to a
genuine defect. Write down the target metric each attempt. If it is not moving monotonically
toward the goal — 26% road, then 43%, then 16% but now flat, then 10% but in the wrong valley
— you are not converging, you are wandering around a space where the model is wrong.

**You are adding parameters.** A new threshold, a new weight, a new cap, a new radius. Each
knob is evidence that the model does not describe the problem, not that it needs tuning.
Three added parameters in a row is a rewrite signal.

**The user has raised the same thing twice.** Their second complaint about the same symptom
outranks your sense of progress completely. It is not a request for another tweak; it is
information that the approach is not landing. Treat it as a hard interrupt.

**You cannot state what "good" looks like as an assertion.** If you cannot write the test,
you do not have the problem specified — and unspecified problems are where tuning goes to
die. Writing it down often makes the right algorithm obvious: "closed, in the distance band,
no road, passes the summit" is four assertions, and the moment they were written the answer
was clearly *search for cycles* rather than *walk out and find a way back*.

**The fix is a penalty rather than a constraint.** If you are making something expensive to
discourage it, and it keeps happening, stop weighting and start removing. A penalty can be
outvoted by every other term; taking the option out of the search space is correct by
construction, and that is a property you can test.

---

## The rule

**Budget the approach, not just the task.** Before the second attempt, decide how many
attempts this approach gets — two or three is usually right — and what the metric is. When
the budget is spent, the next move is *a different approach*, not attempt N+1.

Say it out loud when you set it, and say it out loud when you spend it. "This is the third
time weighting has not fixed it, so I am going to stop weighting and remove roads from the
graph instead" is a far better message than a fourth set of numbers.

---

## When each attempt is expensive

A slow feedback loop — CI, a rate-limited public API, a deploy — ought to make you iterate
less and think more. It reliably does the opposite, because waiting feels like working.

- **Buy the fast loop first.** Pull the input data local, commit a fixture, publish an
  artifact. Whatever it costs, it costs less than six blind rounds. Delete it afterwards.
- **Instrument before you iterate.** Make failure say *what it found*, not that it found
  nothing. "No loop found" cost several rounds. "17 loops in band but more than 25% road;
  230 in band but none within 500 m of the target" identified two distinct bugs in one run.
- **One diagnostic run beats three speculative fixes.** If you cannot say which of two
  theories is right, the next action is a run that distinguishes them, not a change that
  assumes one.

---

## Reporting

**Report the user's metric, not your process.** "CI is green", "the tests pass", "the survey
ran" are not progress if the thing they asked for — a working page, a good result — is
unchanged. Every update should state where that stands, even when the answer is "no better
than last time".

**Separate what you verified from what you believe.** "Deployed successfully" and "I loaded
it and it works" are different claims; conflating them is how a site served the wrong content
for a week under a green tick. If you could not check, say you could not check and say why.

**Do not lead with a remedy that shifts work to the user** — clear your cache, re-run the
job, tick this box — unless you have ruled out the causes you can fix yourself. It is
right often enough to become a habit, and it spends trust badly when the cause was structural.

**Volunteer the sunk cost.** If an approach is being abandoned, say what it cost and what the
signal was. It is the only way the next person, or the next session, does not pay it again.

---

## Context and tokens

Spend them on thinking, not on transport.

- If a tool returns tens of thousands of characters and you need three fields, change
  channel: a targeted API, a `git` command, a filter. Repeatedly paging huge payloads is a
  real cost with no information gain.
- Poll the cheapest thing that answers the question. Watching for a commit with `git fetch`
  beats re-listing every workflow run.
- Do not re-read what you already established. Re-deriving context is the quiet way a long
  session runs out of room to think.

---

## Quick check, before the next attempt

- [ ] What is the metric, and did the last attempt move it in the right direction?
- [ ] How many attempts has *this approach* had? Is it out of budget?
- [ ] Have I added a parameter this round? How many in a row now?
- [ ] Has the user raised this same symptom before?
- [ ] Can I write the success condition as an assertion? Have I?
- [ ] Is my next action a fix, or a run that tells me which fix is right?
