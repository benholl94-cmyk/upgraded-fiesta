CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE IF NOT EXISTS sessions (id UUID PRIMARY KEY, agent_id TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS messages (id UUID PRIMARY KEY, session_id UUID REFERENCES sessions(id), role TEXT NOT NULL, content JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS memories (id UUID PRIMARY KEY, agent_id TEXT NOT NULL, content TEXT NOT NULL, embedding vector(1536), metadata JSONB DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT now());
CREATE INDEX IF NOT EXISTS memories_content_trgm_idx ON memories USING gin (content gin_trgm_ops);
