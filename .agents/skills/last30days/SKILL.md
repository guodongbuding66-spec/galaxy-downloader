---
name: last30days
description: Project-local adapter for researching recent software UI patterns and user expectations from the last 30 days before major redesigns.
source: https://github.com/mvanhorn/last30days-skill
upstream-version: "3.27.2"
upstream-license: MIT
install-mode: project-local-adapter
---

# Last 30 Days - Galaxy UI Research Adapter

Use before a major Galaxy Local Engine UI redesign when fresh evidence would materially improve the result.

This project adapter intentionally does **not** vendor the upstream runtime engine or its optional paid research backends. Use the host's normal public web/GitHub search capabilities. Do not use TinyFish or require paid scraping/API services.

## Research targets

Focus on recent evidence about:

- Professional desktop utilities and media/download managers.
- Windows 11 utility patterns, dense workbenches, settings and task queues.
- Download/capture tools such as video downloaders, asset managers and developer utilities.
- Current complaints users have about readability, excessive card layouts, generic AI aesthetics, clutter, tiny type, weak hierarchy and over-animation.
- Interaction details for progress, retry, queue control, original-image capture and source inspection.

## Method

1. Restrict trend/community evidence to roughly the last 30 days when possible.
2. Prefer primary product docs, GitHub discussions/issues, recent release notes and credible community feedback.
3. Separate stable platform conventions from short-lived visual trends.
4. Summarize what is actually useful for Galaxy; do not copy a fashionable surface blindly.
5. Cite fresh public sources when research materially changes a design decision.

## Guardrails

- Research informs the design; existing Galaxy workflows and user feedback remain stronger evidence.
- Do not turn the application into a web wrapper because a recent product uses one.
- Do not add a trend unless it improves clarity, speed, discoverability or readability.
- Do not use TinyFish, paid scrapers or paid browser automation.
