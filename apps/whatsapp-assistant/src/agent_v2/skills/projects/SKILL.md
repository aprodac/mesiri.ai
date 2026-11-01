# Projects rules

This skill covers **making a new project, or a new site under a project**, from chat. Only an
admin or project manager can; the system refuses anyone else (you do not decide that).

- "Create / add / start a new project ..." is `create_project`; "new site ..." is `create_site`
  (with `project` only when they name one). It shows a Yes / No confirmation; say what you are
  about to create, never that it was created.
- **Never invent a name.** If they describe a project but give no name ("a 7,000 sq ft G+1
  supermarket in Kerala, add it"), call `ask` for the name in one short question. Do not call
  `create_project` until you have it. Never use placeholders like "Project A".
- From a long description take the name, the size (`size_sqft`), the place (`location`) and what
  is being built (`project_type`) yourself; ask only for what is missing (the name first).
  Size and location are optional: never block on them.
- A project name that is one of their projects already (see `my_scope`): do not create it
  again; tell them it exists and offer to send updates for it.
- Renaming a project is not built: pass it on with `tell_the_team` (`missing_feature`).
- If the system says only an admin or project manager can do this, say that, and tell them to ask
  their admin (name the admin if you know who).
- After they confirm, the system says it is created; offer to send updates for it. A new project
  or site can be chosen as the site straight away.
- Same in Malayalam, Manglish and Hindi, typed or by voice ("puthiya project undaakku").
