CREATE TABLE IF NOT EXISTS coordinator.incidents (
 id uuid PRIMARY KEY, case_id uuid NOT NULL, title text NOT NULL,
 patient_id text NOT NULL, reference text NOT NULL,
 request_type text NOT NULL DEFAULT 'FINAL_AUTHORIZATION',
 state text NOT NULL DEFAULT 'AWAITING_CONSENT', decision_state text NOT NULL DEFAULT 'PENDING',
 consent_version integer NOT NULL DEFAULT 0, consent_active boolean NOT NULL DEFAULT false,
 version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.events (
 sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 type text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.complex_workflows (
 incident_id uuid PRIMARY KEY REFERENCES coordinator.incidents(id), data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS coordinator.documents (
 id uuid PRIMARY KEY, incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 filename text NOT NULL, content_type text NOT NULL, kind text NOT NULL,
 content_hash text NOT NULL, data bytea NOT NULL, status text NOT NULL DEFAULT 'UPLOADED_UNVERIFIED',
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.calls (
 id uuid PRIMARY KEY, incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 participant_role text NOT NULL, purpose text NOT NULL, mode text NOT NULL,
 state text NOT NULL DEFAULT 'RECORDED', execution_id text UNIQUE,
 transcript jsonb NOT NULL DEFAULT '[]', recording_consent boolean NOT NULL DEFAULT false,
 recording_url text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.assertions (
 id uuid PRIMARY KEY, incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 call_id uuid REFERENCES coordinator.calls(id), document_id uuid REFERENCES coordinator.documents(id),
 source_role text NOT NULL, predicate text NOT NULL, value jsonb NOT NULL,
 reference text NOT NULL, request_type text NOT NULL, support_status text NOT NULL DEFAULT 'REPORTED',
 supersedes_id uuid REFERENCES coordinator.assertions(id), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.actions (
 id uuid PRIMARY KEY, incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 kind text NOT NULL, payload jsonb NOT NULL, payload_hash text NOT NULL,
 evidence_ids jsonb NOT NULL, consent_version integer NOT NULL,
 state text NOT NULL DEFAULT 'PROPOSED', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.verified_receipts (
 id text PRIMARY KEY, incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 envelope jsonb NOT NULL, signature text NOT NULL, verified_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.command_results (
 key text PRIMARY KEY, body_hash text NOT NULL, response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.webhook_inbox (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, dedupe_key text NOT NULL UNIQUE,
 payload jsonb NOT NULL, processed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.jobs (
 id uuid PRIMARY KEY, incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 kind text NOT NULL, payload jsonb NOT NULL, state text NOT NULL DEFAULT 'QUEUED',
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, last_error text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS coordinator.participants (
 id uuid PRIMARY KEY, incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 role text NOT NULL, phone text NOT NULL, verified boolean NOT NULL,
 demo_consent text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE coordinator.participants ADD COLUMN IF NOT EXISTS recording_consent boolean NOT NULL DEFAULT false;
ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS participant_id uuid REFERENCES coordinator.participants(id);
ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS tool_token_hash text;
ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS consent_version integer;
ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS tool_expires_at timestamptz;
ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS last_polled_at timestamptz;
ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS poll_failures integer NOT NULL DEFAULT 0;

ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS action_id uuid REFERENCES coordinator.actions(id);

DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='coordinator' AND table_name='incidents' AND column_name='is_test') THEN
  ALTER TABLE coordinator.incidents ADD COLUMN is_test boolean NOT NULL DEFAULT false;
  UPDATE coordinator.incidents SET is_test=true WHERE title LIKE '[Integration test] %';
 END IF;
END $$;

ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS workflow_packet_hash text;

CREATE TABLE IF NOT EXISTS coordinator.workflow_callbacks (
 id uuid PRIMARY KEY, incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
 task_key text NOT NULL, purpose text NOT NULL, proposal jsonb NOT NULL,
 consent_version integer NOT NULL, original_received_at timestamptz,
 target_at timestamptz, available_at timestamptz NOT NULL,
 state text NOT NULL DEFAULT 'WAITING', attempts integer NOT NULL DEFAULT 0,
 lease_token uuid, lease_until timestamptz, result jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(incident_id,task_key), CHECK(attempts BETWEEN 0 AND 2)
);
