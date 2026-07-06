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
    pub async fn load(storage: Arc<dyn FileStorage>, key: impl Into<String>) -> Self {
        let key = key.into();
        let state = match storage.get(&key).await {
            Ok(bytes) => serde_json::from_slice(&bytes).unwrap_or_default(),
            Err(_) => MemoryState::default(),
        };
        Self {
            storage,
            key,
            state: RwLock::new(state),
        }
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
        let store = MemoryStore::load(storage, "memory.json").await;

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
            let store = MemoryStore::load(storage.clone(), "memory.json").await;
            store
                .remember("first process wrote this memory")
                .await
                .unwrap();
        }

        let reloaded = MemoryStore::load(storage, "memory.json").await;
        let records = reloaded.list().await;
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].text, "first process wrote this memory");
    }

    // --- knowledge-graph seed ingestion ---

    #[tokio::test]
    async fn graph_is_none_until_ingested() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await;
        assert!(store.graph().await.is_none());
    }

    #[tokio::test]
    async fn ingests_a_well_formed_graph_seed() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await;

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
        let store = MemoryStore::load(storage, "memory.json").await;

        assert!(store.ingest_graph_seed(br#"{"edges":[]}"#).await.is_err());
        assert!(store.ingest_graph_seed(br#"{"nodes":[]}"#).await.is_err());
        assert!(store.ingest_graph_seed(b"not json").await.is_err());
        assert!(store.graph().await.is_none());
    }

    #[tokio::test]
    async fn ingesting_a_graph_never_pollutes_free_text_recall() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await;

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
            let store = MemoryStore::load(storage.clone(), "memory.json").await;
            store
                .ingest_graph_seed(br#"{"nodes":[{"id":"persisted"}],"edges":[]}"#)
                .await
                .unwrap();
        }

        let reloaded = MemoryStore::load(storage, "memory.json").await;
        let graph = reloaded.graph().await.unwrap();
        assert_eq!(graph["nodes"][0]["id"], "persisted");
    }

    #[tokio::test]
    async fn re_ingesting_replaces_rather_than_accumulates() {
        let dir = TempDir::new();
        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let store = MemoryStore::load(storage, "memory.json").await;

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
}
