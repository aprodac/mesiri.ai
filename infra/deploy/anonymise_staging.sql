-- TM-40 (approved by Ilan, 2 Nov 2026, docs/DECISIONS.md): staging holds a copy of production with names and
-- numbers removed, so customer bugs can be reproduced on real-shaped data by people and bots that must never see
-- the real thing. Run by infra/deploy/staging_deploy.sh on mesiri_staging right after the copy, never on production
-- (the first statement refuses any other database).
--
-- What changes:
--   * every person, company (except the team's own test companies), worker, supplier, recipient and project name
--     becomes a stable stand-in ("Person 3F2A"); the SAME stand-in replaces that name inside every message, trace,
--     note and payload, so a conversation still reads the same ("add Person 3F2A to Project 81C0");
--   * every phone number becomes a stand-in (consistently, so a sender still matches their user), and any other run
--     of 8+ digits in free text is masked; emails, addresses, bank details and login codes go;
--   * WhatsApp profile names inside the raw webhook payloads become "Someone"; password hashes and login codes go.
-- Quantities, dates, units, materials, sites and ids stay: they are what reproduces a bug.
-- At the end `staging_anonymised` records when, and how many names / numbers were replaced.

\set ON_ERROR_STOP on

DO $$ BEGIN
  IF current_database() <> 'mesiri_staging' THEN
    RAISE EXCEPTION 'anonymise_staging.sql runs on mesiri_staging only, not %', current_database();
  END IF;
END $$;

BEGIN;

-- The team's own companies keep their names (they are already test data).
CREATE TEMP TABLE keep_orgs AS
  SELECT id FROM organizations
  WHERE name ILIKE ANY (ARRAY['%paraclet%', 'Mesiri Test Builders', '%demo%', '%test%']);

-- Every name, and the stand-in for it. Longest first when replacing, so "Muhammed Sahal" goes before "Sahal".
CREATE TEMP TABLE name_map (old text PRIMARY KEY, new text NOT NULL, pattern text);

CREATE FUNCTION pg_temp.add_names(kind text, names text[]) RETURNS void LANGUAGE plpgsql AS $f$
DECLARE n text; tok text;
BEGIN
  FOREACH n IN ARRAY names LOOP
    n := btrim(n);
    CONTINUE WHEN n IS NULL OR length(n) < 3 OR n ~ '["\\]';
    INSERT INTO name_map (old, new) VALUES (n, kind || ' ' || upper(left(md5(kind || lower(n)), 4)))
      ON CONFLICT (old) DO NOTHING;
    IF kind = 'Person' THEN
      -- First and last names on their own ("Sahal" in a message about "Muhammed Sahal").
      FOREACH tok IN ARRAY regexp_split_to_array(n, '\s+') LOOP
        CONTINUE WHEN length(tok) < 4 OR tok ~ '["\\.]';
        INSERT INTO name_map (old, new) VALUES (tok, 'P-' || upper(left(md5(lower(tok)), 4)))
          ON CONFLICT (old) DO NOTHING;
      END LOOP;
    END IF;
  END LOOP;
END $f$;

SELECT pg_temp.add_names('Person', ARRAY(SELECT full_name FROM users UNION SELECT name FROM workforce_workers
  UNION SELECT worker_name FROM labour_attendance_lines UNION SELECT worker_name_original FROM labour_attendance_lines
  UNION SELECT worker_name FROM labour_attendance_entries UNION SELECT name FROM report_recipients
  UNION SELECT primary_contact FROM organizations));
SELECT pg_temp.add_names('Company', ARRAY(SELECT name FROM organizations WHERE id NOT IN (SELECT id FROM keep_orgs)
  UNION SELECT name FROM vendors UNION SELECT supplier_name FROM material_invoices UNION SELECT supplier FROM material_receipts
  UNION SELECT client FROM projects));
SELECT pg_temp.add_names('Project', ARRAY(SELECT name FROM projects WHERE organization_id NOT IN (SELECT id FROM keep_orgs)));
UPDATE name_map SET pattern = '(?<![[:alnum:]])' || regexp_replace(old, '([.*+?^${}()|\[\]\\])', '\\\1', 'g') || '(?![[:alnum:]])';

-- Phone numbers: one stand-in each, the same wherever the number appears.
CREATE TEMP TABLE phone_map (old text PRIMARY KEY, new text NOT NULL);
INSERT INTO phone_map
  SELECT p, '9199' || lpad((row_number() OVER (ORDER BY p))::text, 8, '0')
  FROM (SELECT whatsapp_number p FROM users UNION SELECT sender_wa_id FROM inbound_messages
        UNION SELECT phone FROM report_recipients UNION SELECT phone FROM whatsapp_opt_ins
        UNION SELECT wa_id FROM whatsapp_group_join_requests UNION SELECT recipient FROM provider_executions
        UNION SELECT phone FROM organizations UNION SELECT phone FROM signup_attempts) x
  WHERE p ~ '\d{8,}';

CREATE FUNCTION pg_temp.phone(p text) RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT CASE WHEN p IS NULL THEN NULL ELSE coalesce((SELECT new FROM phone_map WHERE old = p), regexp_replace(p, '\d', 'x', 'g')) END
$f$;

-- Free text: every mapped name, then every phone, then any other run of 8+ digits that isn't part of an id.
-- `mask` is what a stray 8+ digit run becomes: letters in plain text, digits inside JSON (a bare JSON number must stay
-- a number, or the payload stops being JSON).
CREATE FUNCTION pg_temp.scrub(t text, mask text DEFAULT 'xxxxxxxxxx') RETURNS text LANGUAGE plpgsql STABLE AS $f$
DECLARE r record; low text;
BEGIN
  IF t IS NULL OR t = '' THEN RETURN t; END IF;
  low := lower(t);
  FOR r IN SELECT old, new, pattern FROM name_map ORDER BY length(old) DESC LOOP
    IF position(lower(r.old) IN low) > 0 THEN
      t := regexp_replace(t, r.pattern, r.new, 'gi');
      low := lower(t);
    END IF;
  END LOOP;
  FOR r IN SELECT old, new FROM phone_map LOOP
    IF position(r.old IN t) > 0 THEN t := replace(t, r.old, r.new); END IF;
  END LOOP;
  -- (a stand-in phone, 9199…, is kept: it still points at the same person)
  RETURN regexp_replace(t, '(?<![[:alnum:]-])(?!9199)\d{8,}(?![[:alnum:]-])', mask, 'g');
END $f$;

-- WhatsApp's own profile name (webhook "profile": {"name": …}, and the sender name copied from it) is not in any
-- table, so it is replaced wherever it sits; every other "name" (a project, a material) goes through the map.
CREATE FUNCTION pg_temp.scrub_json(j json) RETURNS json LANGUAGE sql STABLE AS $f$
  SELECT regexp_replace(regexp_replace(pg_temp.scrub(j::text, '9999999999'),
    '("profile"\s*:\s*\{\s*"name"\s*:\s*)"[^"]*"', '\1"Someone"', 'g'),
    '"(profile_name|sender_name)"\s*:\s*"[^"]*"', '"\1": "Someone"', 'g')::json
$f$;
-- The same for jsonb (production keeps some of these columns as jsonb, others as json: one name, both types).
CREATE FUNCTION pg_temp.scrub_json(j jsonb) RETURNS jsonb LANGUAGE sql STABLE AS $f$
  SELECT pg_temp.scrub_json(j::json)::jsonb
$f$;
CREATE FUNCTION pg_temp.scrub_jsonb(j jsonb) RETURNS jsonb LANGUAGE sql STABLE AS $f$
  SELECT pg_temp.scrub(j::text, '9999999999')::jsonb
$f$;
CREATE FUNCTION pg_temp.scrub_jsonb(j json) RETURNS json LANGUAGE sql STABLE AS $f$
  SELECT pg_temp.scrub(j::text, '9999999999')::json
$f$;

-- People and companies, in their own columns.
UPDATE users SET full_name = coalesce((SELECT new FROM name_map WHERE old = btrim(full_name)), full_name),
  email = CASE WHEN email IS NULL THEN NULL ELSE 'user-' || left(md5(id::text), 10) || '@example.invalid' END,
  username = CASE WHEN username IS NULL THEN NULL ELSE 'user-' || left(md5(id::text), 10) END,
  whatsapp_number = pg_temp.phone(whatsapp_number),
  hashed_password = 'disabled-on-staging';  -- no real password hash leaves production (nobody logs in to staging)
UPDATE organizations SET
  name = CASE WHEN id IN (SELECT id FROM keep_orgs) THEN name ELSE coalesce((SELECT new FROM name_map WHERE old = btrim(organizations.name)), name) END,
  primary_contact = coalesce((SELECT new FROM name_map WHERE old = btrim(primary_contact)), CASE WHEN primary_contact IS NULL THEN NULL ELSE 'Someone' END),
  address = NULL, email = NULL, phone = pg_temp.phone(phone);
UPDATE projects SET name = coalesce((SELECT new FROM name_map WHERE old = btrim(projects.name)), name),
  client = coalesce((SELECT new FROM name_map WHERE old = btrim(client)), client),
  location = NULL, description = pg_temp.scrub(description)
  WHERE organization_id NOT IN (SELECT id FROM keep_orgs);
UPDATE workforce_workers SET name = coalesce((SELECT new FROM name_map WHERE old = btrim(name)), name);
UPDATE labour_attendance_lines SET worker_name = coalesce((SELECT new FROM name_map WHERE old = btrim(worker_name)), worker_name),
  worker_name_original = coalesce((SELECT new FROM name_map WHERE old = btrim(worker_name_original)), worker_name_original),
  remarks = pg_temp.scrub(remarks);
UPDATE labour_attendance_entries SET worker_name = coalesce((SELECT new FROM name_map WHERE old = btrim(worker_name)), worker_name);
UPDATE report_recipients SET name = coalesce((SELECT new FROM name_map WHERE old = btrim(name)), name), phone = pg_temp.phone(phone);
UPDATE vendors SET name = coalesce((SELECT new FROM name_map WHERE old = btrim(name)), name);
UPDATE material_invoices SET supplier_name = coalesce((SELECT new FROM name_map WHERE old = btrim(supplier_name)), supplier_name), notes = pg_temp.scrub(notes);
UPDATE material_receipts SET supplier = coalesce((SELECT new FROM name_map WHERE old = btrim(supplier)), supplier), notes = pg_temp.scrub(notes);
UPDATE material_usage SET notes = pg_temp.scrub(notes);
UPDATE money_accounts SET account_number_last4 = CASE WHEN account_number_last4 IS NULL THEN NULL ELSE '0000' END,
  ifsc = NULL, bank_name = CASE WHEN bank_name IS NULL THEN NULL ELSE 'Bank' END, name = pg_temp.scrub(name);
UPDATE money_transactions SET description = pg_temp.scrub(description);
UPDATE expenses SET description = pg_temp.scrub(description);
DELETE FROM login_codes;
UPDATE signup_attempts SET phone = pg_temp.phone(phone), ip_address = NULL;
UPDATE whatsapp_opt_ins SET phone = pg_temp.phone(phone), note = pg_temp.scrub(note);
UPDATE whatsapp_group_join_requests SET wa_id = pg_temp.phone(wa_id);
UPDATE provider_executions SET recipient = pg_temp.phone(recipient);

-- Customers' own words, Mesiri's replies, and everything recorded from them.
UPDATE inbound_messages SET sender_wa_id = pg_temp.phone(sender_wa_id), body_text = pg_temp.scrub(body_text),
  body_text_en = pg_temp.scrub(body_text_en), assistant_reply = pg_temp.scrub(assistant_reply),
  normalized_message = pg_temp.scrub_json(normalized_message), raw_payload = pg_temp.scrub_json(raw_payload);
UPDATE journey_traces SET stage_payload = pg_temp.scrub_json(stage_payload), error_message = pg_temp.scrub(error_message);
UPDATE notifications SET payload = pg_temp.scrub_jsonb(payload);
UPDATE timeline_entries SET payload = pg_temp.scrub_jsonb(payload), summary = pg_temp.scrub(summary);
UPDATE outbox_events SET payload = pg_temp.scrub_jsonb(payload);
UPDATE daily_report_versions SET payload = pg_temp.scrub_jsonb(payload), narrative_summary = pg_temp.scrub(narrative_summary);
UPDATE progress_attachments SET caption = pg_temp.scrub(caption), ai_caption = pg_temp.scrub(ai_caption);
UPDATE site_issues SET narrative = pg_temp.scrub(narrative), resolution_notes = pg_temp.scrub(resolution_notes);
UPDATE labour_attendance_reports SET notes = pg_temp.scrub(notes), void_reason = pg_temp.scrub(void_reason);
UPDATE automations SET message = pg_temp.scrub(message);

-- The marker: anything that hands staging to a person or a bot checks it is there.
CREATE TABLE IF NOT EXISTS staging_anonymised (at timestamptz NOT NULL, names int NOT NULL, phones int NOT NULL);
INSERT INTO staging_anonymised SELECT now(), (SELECT count(*) FROM name_map), (SELECT count(*) FROM phone_map);

COMMIT;

SELECT 'anonymised: ' || names || ' names, ' || phones || ' phone numbers replaced' AS result FROM staging_anonymised ORDER BY at DESC LIMIT 1;
