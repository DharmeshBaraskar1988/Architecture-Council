-- Phase 1 database schema (PostgreSQL 16 + pgvector). Loaded by docker compose on first start.
-- Week 1: schema only; the code writes run files. Wiring to these tables is Week 2 (task 1.8).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, document TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'production',
  settings JSONB NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'running',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS doc_chunks (
  id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id), page INT, text TEXT,
  embedding vector(384));                                   -- bge-small-en-v1.5 size

CREATE TABLE IF NOT EXISTS events (
  session_id TEXT REFERENCES sessions(id), seq INT, type TEXT, stage TEXT,
  payload JSONB, at TIMESTAMPTZ, PRIMARY KEY (session_id, seq));

CREATE TABLE IF NOT EXISTS web_pages (
  id TEXT PRIMARY KEY, url TEXT UNIQUE, domain TEXT, title TEXT, text TEXT,
  fetched_at TIMESTAMPTZ, content_hash TEXT);

CREATE TABLE IF NOT EXISTS web_chunks (
  id TEXT PRIMARY KEY, page_id TEXT REFERENCES web_pages(id), text TEXT, embedding vector(384));

-- The decision database: every signed decision becomes a precedent for later sessions.
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY, session_id TEXT, project TEXT, stage TEXT, subject TEXT,
  outcome TEXT, agreement NUMERIC, vote_support NUMERIC, evidence_balance NUMERIC,
  rationale TEXT, dissent TEXT, conditions TEXT, evidence JSONB, reviewer TEXT,
  reviewer_override_reason TEXT, is_sample BOOLEAN NOT NULL DEFAULT false,
  decided_at TIMESTAMPTZ NOT NULL DEFAULT now(), embedding vector(384));

CREATE TABLE IF NOT EXISTS gate_results (
  candidate_id TEXT, capability TEXT, verdict TEXT, reasons JSONB, evidence JSONB,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (candidate_id, checked_at));
