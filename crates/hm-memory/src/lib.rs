use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use hm_storage::FileStorage;
use hm_vector::{embed, VectorIndex, DEFAULT_DIMS};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::sync::RwLock;
use uuid::Uuid;

pub fn component_name() -> &'static str {
    "hm-memory"
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryRecord {
    pub id: String,
    pub text: String,
    pub created_at_unix: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct MemoryState {
    records: Vec<MemoryRecord>,
    index: VectorIndex,
    /// A structural knowledge-graph seed (the `{"nodes":[...],"edges":[...]}`
    /// shape `scripts/generate_knowledge_graph_seed.py` produces), kept
    /// entirely separate from `records`/`index` -- never blended into
    /// free-text recall results, exposed only via [`MemoryStore::graph`].
    #[serde(default)]
    graph: Option<Value>,
}

/// A persistent, semantically-searchable text memory. Backed by any
/// [`FileStorage`] (in production, `hm-storage`'s local-disk implementation),
/// so it survives process restarts. Embeddings are the offline lexical
/// hashing-trick scheme from `hm-vector` -- no external model or API key.
pub struct MemoryStore {
    storage: Arc<dyn FileStorage>,
    key: String,
    state: RwLock<MemoryState>,
}

impl MemoryStore {
    /// Loads existing state from `key` in `storage`, or starts empty if
    /// nothing is stored there yet.
    ///
    /// **"Nothing stored yet" and "stored, but unreadable" are different
    /// answers and must not collapse into the same one.** This used to be
    /// `serde_json::from_slice(&bytes).unwrap_or_default()` with
    /// `Err(_) => MemoryState::default()`, so a corrupt file, a permission
    /// error or an unreachable remote backend all produced an empty memory.
    ///
    /// Reproduced end to end before the fix: three stored records, the state
    /// file truncated to 4000 of 7348 bytes, gateway restarted. It started
    /// normally, logged nothing, answered `GET /memory` with zero records —
    /// and the very next write persisted that empty state over the file,
    /// destroying the three records permanently. `persist()` runs on every
    /// `remember()`, and `hm-agent` records one entry per dispatched task, so
    /// the window between "silently empty" and "irreversibly gone" is seconds.
    ///
    /// Failing to start is the right answer, and it is the house rule already:
    /// the gateway refuses to start on a missing `HM_OWNER_TOKEN` and on a
    /// misconfigured remote storage backend rather than degrade quietly. An
    /// operator can then inspect or move the file; a silently emptied memory
    /// gives them nothing to inspect.
    pub async fn load(
        storage: Arc<dyn FileStorage>,
        key: impl Into<String>,
    ) -> anyhow::Result<Self> {
        let key = key.into();

        // `get` returns one opaque error for "absent" and for "present but
        // unreadable", so the distinction is asked for separately. A false
        // `exists` is the only case that may legitimately start empty --
        // and a *failed* existence check is not a false one: for the remote
        // backend it means the storage host answered 5xx or was unreachable,
        // for the local one it means the path could not be stat'ed. Treating
        // either as "no memory yet" would rebuild the exact bug this function
        // exists to remove.
        let exists = storage.exists(&key).await.map_err(|error| {
            anyhow::anyhow!(
                "cannot determine whether memory state '{key}' exists: {error}. \
                 Refusing to start, because assuming 'no memory yet' would \
                 overwrite it on the next write."
            )
        })?;

        let state = if exists {
            let bytes = storage.get(&key).await.map_err(|error| {
                anyhow::anyhow!(
                    "memory state '{key}' exists but could not be read: {error}. \
                     Refusing to start with an empty memory -- continuing would \
                     overwrite the stored state on the next write."
                )
            })?;
            serde_json::from_slice(&bytes).map_err(|error| {
                anyhow::anyhow!(
                    "memory state '{key}' is present but not valid JSON: {error}. \
                     Refusing to start with an empty memory -- continuing would \
                     overwrite it on the next write. Move the file aside to start fresh."
                )
            })?
        } else {
            MemoryState::default()
        };

        Ok(Self {
            storage,
            key,
            state: RwLock::new(state),
        })
    }

    /// Embeds and persists `text`, returning the stored record.
    pub async fn remember(&self, text: impl Into<String>) -> anyhow::Result<MemoryRecord> {
        let text = text.into();
        let vector = embed(&text, DEFAULT_DIMS);
        let record = MemoryRecord {
            id: format!("mem-{}", Uuid::new_v4()),
            text,
            created_at_unix: unix_now(),
        };

        {
            let mut state = self.state.write().await;
            state.index.insert(record.id.clone(), vector);
            state.records.push(record.clone());
        }
        self.persist().await?;
        Ok(record)
    }

    /// Returns up to `top_k` stored records ranked by similarity to `query`.
    pub async fn recall(&self, query: &str, top_k: usize) -> Vec<(MemoryRecord, f32)> {
        let query_vector = embed(query, DEFAULT_DIMS);
        let state = self.state.read().await;
        state
            .index
            .search(&query_vector, top_k)
            .into_iter()
            .filter_map(|(id, score)| {
                state
                    .records
                    .iter()
                    .find(|record| record.id == id)
                    .map(|record| (record.clone(), score))
            })
            .collect()
    }

    pub async fn list(&self) -> Vec<MemoryRecord> {
        self.state.read().await.records.clone()
    }

    /// Ingests a knowledge-graph seed -- the `{"nodes":[...],"edges":[...]}`
    /// shape `scripts/generate_knowledge_graph_seed.py` produces -- storing
    /// it distinctly from free-text memory records. Replaces any
    /// previously-ingested graph (there is exactly one graph per store, not
    /// an accumulating list); persisted immediately so a restart doesn't
    /// lose it.
    pub async fn ingest_graph_seed(&self, graph_json: &[u8]) -> anyhow::Result<()> {
        let graph: Value = serde_json::from_slice(graph_json)?;
        if graph.get("nodes").is_none() || graph.get("edges").is_none() {
            anyhow::bail!("graph seed JSON must have both 'nodes' and 'edges' fields");
        }
        {
            let mut state = self.state.write().await;
            state.graph = Some(graph);
        }
        self.persist().await
    }

    /// The most recently ingested graph seed, or `None` if nothing has been
    /// ingested yet.
    pub async fn graph(&self) -> Option<Value> {
        self.state.read().await.graph.clone()
    }

    async fn persist(&self) -> anyhow::Result<()> {
        let bytes = {
            let state = self.state.read().await;
            serde_json::to_vec(&*state)?
        };
        self.storage.put(&self.key, &bytes).await
    }
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

#[cfg(test)]
mod tests {
    use super::*;
    use hm_storage::LocalFsStorage;
    use std::path::PathBuf;

    struct TempDir(PathBuf);
    impl TempDir {
        fn new() -> Self {
            Self(std::env::temp_dir().join(format!("hm-memory-test-{}", Uuid::new_v4())))
        }
    }
    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[tokio::test]
    async fn remember_and_recall_roundtrip() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await.unwrap();

        store
            .remember("the gateway exposes a storage API")
            .await
            .unwrap();
        store
            .remember("bananas are a tropical fruit")
            .await
            .unwrap();

        let hits = store.recall("storage api on the gateway", 1).await;
        assert_eq!(hits.len(), 1);
        assert!(hits[0].0.text.contains("storage API"));
    }

    #[tokio::test]
    async fn state_persists_across_reload() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));

        {
            let store = MemoryStore::load(storage.clone(), "memory.json")
                .await
                .unwrap();
            store
                .remember("first process wrote this memory")
                .await
                .unwrap();
        }

        let reloaded = MemoryStore::load(storage, "memory.json").await.unwrap();
        let records = reloaded.list().await;
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].text, "first process wrote this memory");
    }

    // --- knowledge-graph seed ingestion ---

    #[tokio::test]
    async fn graph_is_none_until_ingested() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await.unwrap();
        assert!(store.graph().await.is_none());
    }

    #[tokio::test]
    async fn ingests_a_well_formed_graph_seed() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await.unwrap();

        let seed = br#"{"nodes":[{"id":"crate:hm-gateway","type":"crate"}],"edges":[],"node_count":1,"edge_count":0}"#;
        store.ingest_graph_seed(seed).await.unwrap();

        let graph = store.graph().await.unwrap();
        assert_eq!(graph["node_count"], 1);
        assert_eq!(graph["nodes"][0]["id"], "crate:hm-gateway");
    }

    #[tokio::test]
    async fn rejects_a_seed_missing_nodes_or_edges() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await.unwrap();

        assert!(store.ingest_graph_seed(br#"{"edges":[]}"#).await.is_err());
        assert!(store.ingest_graph_seed(br#"{"nodes":[]}"#).await.is_err());
        assert!(store.ingest_graph_seed(b"not json").await.is_err());
        assert!(store.graph().await.is_none());
    }

    #[tokio::test]
    async fn ingesting_a_graph_never_pollutes_free_text_recall() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await.unwrap();

        store.remember("a real free-text memory").await.unwrap();
        store
            .ingest_graph_seed(br#"{"nodes":[{"id":"x"}],"edges":[]}"#)
            .await
            .unwrap();

        let records = store.list().await;
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].text, "a real free-text memory");
    }

    #[tokio::test]
    async fn ingested_graph_survives_reload() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));

        {
            let store = MemoryStore::load(storage.clone(), "memory.json")
                .await
                .unwrap();
            store
                .ingest_graph_seed(br#"{"nodes":[{"id":"persisted"}],"edges":[]}"#)
                .await
                .unwrap();
        }

        let reloaded = MemoryStore::load(storage, "memory.json").await.unwrap();
        let graph = reloaded.graph().await.unwrap();
        assert_eq!(graph["nodes"][0]["id"], "persisted");
    }

    #[tokio::test]
    async fn re_ingesting_replaces_rather_than_accumulates() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await.unwrap();

        store
            .ingest_graph_seed(br#"{"nodes":[{"id":"first"}],"edges":[]}"#)
            .await
            .unwrap();
        store
            .ingest_graph_seed(br#"{"nodes":[{"id":"second"}],"edges":[]}"#)
            .await
            .unwrap();

        let graph = store.graph().await.unwrap();
        assert_eq!(graph["nodes"].as_array().unwrap().len(), 1);
        assert_eq!(graph["nodes"][0]["id"], "second");
    }

    // ── Corrupt state must not become silent data loss ───────────────────────
    //
    // Reproduced against a live gateway before the fix: three records, state
    // file truncated to 4000 of 7348 bytes, restart. The gateway came up
    // normally, logged nothing, answered `GET /memory` with zero records, and
    // the next write persisted that empty state over the file. The three
    // records were gone, with no error at any point.

    /// A file that is present but unparseable must fail loudly, not silently
    /// become an empty memory that overwrites it on the next write.
    #[tokio::test]
    async fn a_corrupt_state_file_is_an_error_not_an_empty_memory() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));

        {
            let store = MemoryStore::load(storage.clone(), "memory.json")
                .await
                .unwrap();
            store
                .remember("this must survive a bad restart")
                .await
                .unwrap();
        }

        // Exactly the shape a torn write leaves behind: a valid prefix.
        let path = dir.0.join("memory.json");
        let full = std::fs::read(&path).unwrap();
        std::fs::write(&path, &full[..full.len() / 2]).unwrap();

        let result = MemoryStore::load(storage.clone(), "memory.json").await;
        assert!(
            result.is_err(),
            "a truncated state file must not load as an empty memory"
        );
        let message = result.err().unwrap().to_string();
        assert!(
            message.contains("memory.json"),
            "the error must name the file so it can be inspected: {message}"
        );

        // And the damaged file is still there to be recovered from.
        assert_eq!(std::fs::read(&path).unwrap().len(), full.len() / 2);
    }

    /// The counter-direction: a *missing* file is not an error. Without this,
    /// fail-closed would make a first start impossible.
    #[tokio::test]
    async fn an_absent_state_file_starts_empty_without_complaint() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await.unwrap();
        assert!(store.list().await.is_empty());
    }

    /// Storage that fails its existence check must not be read as "nothing
    /// stored yet" -- for the remote backend that would be an unreachable
    /// host, and starting empty would overwrite the remote state.
    #[tokio::test]
    async fn a_failing_existence_check_is_an_error_not_an_empty_memory() {
        struct BrokenStorage;

        #[async_trait::async_trait]
        impl FileStorage for BrokenStorage {
            async fn put(&self, _key: &str, _bytes: &[u8]) -> anyhow::Result<()> {
                Ok(())
            }
            async fn get(&self, _key: &str) -> anyhow::Result<Vec<u8>> {
                anyhow::bail!("storage host unreachable")
            }
            async fn delete(&self, _key: &str) -> anyhow::Result<bool> {
                Ok(true)
            }
            async fn exists(&self, _key: &str) -> anyhow::Result<bool> {
                anyhow::bail!("storage host unreachable")
            }
        }

        let storage: Arc<dyn FileStorage> = Arc::new(BrokenStorage);
        assert!(
            MemoryStore::load(storage, "memory.json").await.is_err(),
            "an unreachable backend must not present itself as an empty memory"
        );
    }
}
