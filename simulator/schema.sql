CREATE SCHEMA IF NOT EXISTS hospital;
CREATE SCHEMA IF NOT EXISTS claims;
CREATE SCHEMA IF NOT EXISTS coordinator;

CREATE TABLE IF NOT EXISTS hospital.cases (
 id uuid PRIMARY KEY, run_id uuid NOT NULL, patient_alias text NOT NULL,
 patient_id text NOT NULL, admission_id text NOT NULL,
 initial_reference text NOT NULL, initial_status text NOT NULL,
 final_reference text NOT NULL, medical_status text NOT NULL,
 packet jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS hospital.submissions (
 id uuid PRIMARY KEY, case_id uuid NOT NULL REFERENCES hospital.cases(id),
 reference text NOT NULL, request_type text NOT NULL CHECK (request_type='FINAL_AUTHORIZATION'),
 revision integer NOT NULL CHECK (revision>0), destination text NOT NULL,
 packet jsonb NOT NULL, packet_hash text NOT NULL, dispatched_at timestamptz NOT NULL,
 transport_status text NOT NULL, delivery_state text NOT NULL,
 idempotency_key text NOT NULL UNIQUE, body_hash text NOT NULL,
 UNIQUE(case_id,revision)
);
CREATE TABLE IF NOT EXISTS claims.routes (
 id text PRIMARY KEY, organization text NOT NULL, destination text NOT NULL UNIQUE,
 request_type text NOT NULL, active boolean NOT NULL
);
CREATE TABLE IF NOT EXISTS claims.requests (
 id uuid PRIMARY KEY, case_id uuid NOT NULL, submission_id uuid NOT NULL UNIQUE,
 patient_id text NOT NULL, reference text NOT NULL, request_type text NOT NULL,
 revision integer NOT NULL, packet_hash text NOT NULL, route_id text NOT NULL REFERENCES claims.routes(id),
 received_at timestamptz NOT NULL, decision_status text NOT NULL DEFAULT 'PENDING'
);
CREATE TABLE IF NOT EXISTS claims.receipts (
 id uuid PRIMARY KEY, request_id uuid NOT NULL UNIQUE REFERENCES claims.requests(id),
 envelope jsonb NOT NULL, signature text NOT NULL
);
CREATE TABLE IF NOT EXISTS claims.lookups (
 id uuid PRIMARY KEY, case_id uuid NOT NULL, scope jsonb NOT NULL,
 result_count integer NOT NULL, performed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS claims.test_controls (
 case_id uuid PRIMARY KEY, withhold_receipt boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS hospital.complex_cases (
 id uuid PRIMARY KEY, data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS claims.complex_cases (
 id uuid PRIMARY KEY, data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS coordinator.schema_version (
 version integer PRIMARY KEY, installed_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO coordinator.schema_version(version) VALUES(1) ON CONFLICT DO NOTHING;

REVOKE ALL ON SCHEMA hospital,claims,coordinator FROM PUBLIC;
GRANT USAGE ON SCHEMA hospital TO claim911_hospital;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA hospital TO claim911_hospital;
GRANT USAGE ON SCHEMA claims TO claim911_claims;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA claims TO claim911_claims;
GRANT USAGE, CREATE ON SCHEMA coordinator TO claim911_core;
GRANT ALL ON ALL TABLES IN SCHEMA coordinator TO claim911_core;
