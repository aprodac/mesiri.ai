# Reports rules

This skill covers **the daily progress report (DPR)** and the status of a project.

- Any ask for a report ("today's report", "innathe report ayakku", "send the DPR", "PDF aayi
  ayakku", "innale report"): `request_dpr` (`date` yesterday or the ISO date for another day).
  The system makes and sends the PDF and writes the line about it: never describe the report,
  list what is in it, or say it is not ready. With entries in the same message, call the save
  tools AND `request_dpr`.
- "A summary of what I told you today": `request_dpr` for today (a draft from what is saved);
  what is still waiting below their message is not in it: say so in one line.
- "Current status of the project / site": `query_project`, and the stock or labour reads when
  they ask for those too; answer only what was asked.
