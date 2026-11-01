# Reports rules

This skill covers **the daily progress report (DPR)** and the status of a project.

- Any ask for a report, for any day -> `request_dpr` (with `date` for another day). The system
  makes and sends it and writes the line about it: never describe it or say it is not ready.
  Entries in the same message are saved too.
- A summary of what they told you today is `request_dpr` for today; what still waits below is not
  in it: say so in one line.
- The status of a project or site -> `query_project` (and the stock or labour reads when asked).
