use serde::{Deserialize, Serialize};

pub const NAME: &str = "vector";

/// Default embedding width for [`embed`].
pub const DEFAULT_DIMS: usize = 256;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VectorRecord {
    pub id: String,
    pub vector: Vec<f32>,
}

/// Brute-force cosine-similarity index. Fine for small/medium corpora kept
/// in memory and persisted as a flat file; this is not a scalable ANN index.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct VectorIndex {
    records: Vec<VectorRecord>,
}

impl VectorIndex {
    pub fn new() -> Self {
        Self::default()
    }

    /// Inserts `vector` under `id`, replacing any existing entry for that id.
    pub fn insert(&mut self, id: impl Into<String>, vector: Vec<f32>) {
        let id = id.into();
        self.records.retain(|record| record.id != id);
        self.records.push(VectorRecord { id, vector });
    }

    pub fn remove(&mut self, id: &str) {
        self.records.retain(|record| record.id != id);
    }

    pub fn len(&self) -> usize {
        self.records.len()
    }

    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }

    /// Returns up to `top_k` ids ranked by cosine similarity to `query`,
    /// highest first.
    pub fn search(&self, query: &[f32], top_k: usize) -> Vec<(String, f32)> {
        let mut scored: Vec<(String, f32)> = self
            .records
            .iter()
            .map(|record| (record.id.clone(), cosine_similarity(&record.vector, query)))
            .collect();
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(top_k);
        scored
    }
}

pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let norm_a = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    dot / (norm_a * norm_b)
}

/// Deterministic, fully offline embedding (no model, no network, no API
/// key): a signed hashing-trick bag-of-words. Text sharing more words scores
/// higher on cosine similarity. This captures lexical overlap, not learned
/// semantics -- a real deep embedding model would need external infra and is
/// deliberately not implied here.
pub fn embed(text: &str, dims: usize) -> Vec<f32> {
    let mut vector = vec![0f32; dims.max(1)];
    for token in text.to_lowercase().split_whitespace() {
        let hash = fnv1a(token);
        let idx = (hash as usize) % vector.len();
        let sign = if (hash >> 63) & 1 == 1 { -1.0 } else { 1.0 };
        vector[idx] += sign;
    }
    let norm = vector.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm > 0.0 {
        for value in vector.iter_mut() {
            *value /= norm;
        }
    }
    vector
}

fn fnv1a(token: &str) -> u64 {
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in token.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embed_is_deterministic() {
        assert_eq!(embed("hello world", 64), embed("hello world", 64));
    }

    #[test]
    fn similar_text_scores_higher_than_unrelated() {
        let base = embed(
            "the gateway accepts local file storage requests",
            DEFAULT_DIMS,
        );
        let similar = embed(
            "the gateway accepts local storage upload requests",
            DEFAULT_DIMS,
        );
        let unrelated = embed(
            "bananas are a tropical fruit grown in warm climates",
            DEFAULT_DIMS,
        );
        assert!(cosine_similarity(&base, &similar) > cosine_similarity(&base, &unrelated));
    }

    #[test]
    fn search_ranks_closest_match_first() {
        let mut index = VectorIndex::new();
        index.insert("a", embed("rust workspace gateway storage", DEFAULT_DIMS));
        index.insert(
            "b",
            embed("bananas tropical fruit warm climate", DEFAULT_DIMS),
        );
        index.insert(
            "c",
            embed("gateway storage rust workspace crate", DEFAULT_DIMS),
        );

        let query = embed("rust gateway storage workspace", DEFAULT_DIMS);
        let results = index.search(&query, 2);

        assert_eq!(results.len(), 2);
        assert!(results[0].0 == "a" || results[0].0 == "c");
        assert!(results.iter().all(|(id, _)| id != "b"));
    }

    #[test]
    fn upsert_replaces_existing_entry() {
        let mut index = VectorIndex::new();
        index.insert("a", vec![1.0, 0.0]);
        index.insert("a", vec![0.0, 1.0]);
        assert_eq!(index.len(), 1);
    }
}
