// hm-vector — Semantischer Vektorindex
//
// Zwei eigenentwickelte Algorithmen ohne externe Abhängigkeiten:
//
//   embed():       Dreifach-Hash-Ensemble mit Bigrams + Trigrams (512 Dims)
//   VectorIndex:   NSW-Graph (Navigable Small World) für O(log n)-ANN-Suche
//
// Das Embedding kombiniert FNV-1a, DJB2 und SDBM in drei disjunkte
// Vektor-Drittel plus Zeichen-N-Gramme für subwortbasierte Ähnlichkeit.
// NSW ist der Kern des bekannten HNSW-Algorithmus, hier als Single-Layer
// implementiert — ausreichend für Korpora bis ~500 K Einträge.

use serde::{Deserialize, Serialize};
use std::collections::HashSet;

pub const NAME: &str = "vector";
pub const EMBED_DIMS: usize = 512;

/// Alias für Rückwärtskompatibilität mit hm-memory.
pub const DEFAULT_DIMS: usize = EMBED_DIMS;

const NSW_M: usize = 16;
const NSW_EF: usize = 32;

// ── Hash-Funktionen ──────────────────────────────────────────────────────────

fn fnv1a(s: &str) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in s.bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

fn djb2(s: &str) -> u64 {
    let mut h: u64 = 5381;
    for b in s.bytes() {
        h = h.wrapping_mul(33).wrapping_add(b as u64);
    }
    h
}

fn sdbm(s: &str) -> u64 {
    let mut h: u64 = 0;
    for b in s.bytes() {
        h = (b as u64)
            .wrapping_add(h.wrapping_shl(6))
            .wrapping_add(h.wrapping_shl(16))
            .wrapping_sub(h);
    }
    h
}

// ── Embedding ────────────────────────────────────────────────────────────────

/// Bettet `text` in einen L2-normierten Vektor der Länge `dims` ein.
///
/// Verwendet ein Dreifach-Hash-Ensemble (FNV-1a + DJB2 + SDBM) über
/// Wörter, Bigrams und Trigramme.  Der zurückgegebene Vektor ist immer
/// L2-normiert (Euklidische Norm ≈ 1), sofern der Text nicht leer ist.
/// Für leere Strings wird ein Nullvektor zurückgegeben.
pub fn embed(text: &str, dims: usize) -> Vec<f32> {
    let dims = dims.max(3);
    let mut v = vec![0.0f32; dims];
    let t0 = dims / 3;
    let t1 = 2 * (dims / 3);

    let tokens: Vec<String> = text
        .split(|c: char| !c.is_alphanumeric())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_lowercase())
        .collect();

    let n = tokens.len().max(1) as f32;

    for (pos, tok) in tokens.iter().enumerate() {
        let pw = 1.0 - (pos as f32 / (n * 2.5)).min(0.4);

        let h1 = fnv1a(tok);
        let i1 = (h1 as usize) % t0;
        v[i1] += if (h1 >> 63) & 1 == 1 { -pw } else { pw };

        let h2 = djb2(tok);
        let i2 = t0 + (h2 as usize) % (t1 - t0);
        v[i2] += if (h2 >> 63) & 1 == 1 { -pw } else { pw };

        let h3 = sdbm(tok);
        let i3 = t1 + (h3 as usize) % (dims - t1);
        v[i3] += if (h3 >> 63) & 1 == 1 { -pw } else { pw };

        let cs: Vec<char> = tok.chars().collect();
        for w in cs.windows(2) {
            let bg = format!("{}{}", w[0], w[1]);
            let hb = fnv1a(&bg);
            let ib = (hb as usize) % dims;
            v[ib] += if (hb >> 32) & 1 == 1 { -0.4 } else { 0.4 };
        }
        for w in cs.windows(3) {
            let tg = format!("{}{}{}", w[0], w[1], w[2]);
            let ht = djb2(&tg);
            let it = (ht as usize) % dims;
            v[it] += if (ht >> 32) & 1 == 1 { -0.25 } else { 0.25 };
        }
    }

    let norm: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm > 1e-9 {
        for x in v.iter_mut() {
            *x /= norm;
        }
    }
    v
}

/// Berechnet die Kosinus-Ähnlichkeit zwischen zwei L2-normierten Vektoren.
///
/// **Vorbedingung**: Beide Vektoren müssen L2-normiert sein (Euklidische Norm ≈ 1).
/// `embed()` liefert stets normierte Vektoren; wer rohe Vektoren über
/// `VectorIndex::insert()` einfügt, muss sie vorher selbst normieren.
/// Der Rückgabewert liegt im Intervall `[-1.0, 1.0]`.
pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    debug_assert_eq!(a.len(), b.len(), "cosine_similarity: vector length mismatch");
    debug_assert!(
        (a.iter().map(|x| x * x).sum::<f32>().sqrt() - 1.0).abs() < 0.01 || a.iter().all(|x| *x == 0.0),
        "cosine_similarity: vector `a` is not L2-normalised — call embed() or normalise first"
    );
    a.iter().zip(b).map(|(x, y)| x * y).sum::<f32>().clamp(-1.0, 1.0)
}

// ── VectorRecord (Compat) ────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VectorRecord {
    pub id: String,
    pub vector: Vec<f32>,
}

// ── NSW-Graph-Index ──────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
struct NswNode {
    id: String,
    vector: Vec<f32>,
    neighbors: Vec<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct VectorIndex {
    nodes: Vec<NswNode>,
    entry: Option<usize>,
}

impl VectorIndex {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    fn beam_search(&self, query: &[f32], ef: usize) -> Vec<(usize, f32)> {
        let Some(ep) = self.entry else {
            return vec![];
        };
        let ep_sim = cosine_similarity(query, &self.nodes[ep].vector);
        let mut candidates: Vec<(usize, f32)> = vec![(ep, ep_sim)];
        let mut result: Vec<(usize, f32)> = vec![(ep, ep_sim)];
        let mut visited: HashSet<usize> = HashSet::new();
        visited.insert(ep);

        while !candidates.is_empty() {
            let best_pos = candidates
                .iter()
                .enumerate()
                .max_by(|a, b| a.1 .1.partial_cmp(&b.1 .1).unwrap())
                .map(|(i, _)| i)
                .unwrap();
            let (best_idx, best_sim) = candidates.swap_remove(best_pos);

            if result.len() >= ef {
                let worst = result.iter().map(|(_, s)| *s).fold(f32::MAX, f32::min);
                if best_sim < worst {
                    break;
                }
            }

            for &nb in &self.nodes[best_idx].neighbors {
                if visited.contains(&nb) {
                    continue;
                }
                visited.insert(nb);
                let sim = cosine_similarity(query, &self.nodes[nb].vector);
                candidates.push((nb, sim));
                result.push((nb, sim));
            }

            if result.len() > ef * 3 {
                result.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
                result.truncate(ef);
            }
        }

        result.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
        result.truncate(ef);
        result
    }

    /// Fügt einen Vektor ein oder ersetzt einen bestehenden Eintrag gleicher ID
    /// (Upsert). `vector` muss L2-normiert sein — vorzugsweise via `embed()`.
    /// Nach einem Upsert wird der NSW-Einstiegspunkt auf den Knoten mit der
    /// höchsten Ähnlichkeit zum gelöschten Vektor gesetzt, um die Suchqualität
    /// zu erhalten.
    pub fn insert(&mut self, id: impl Into<String>, vector: Vec<f32>) {
        let id = id.into();

        if let Some(old) = self.nodes.iter().position(|n| n.id == id) {
            let old_vec = self.nodes[old].vector.clone();
            self.nodes.remove(old);
            for node in self.nodes.iter_mut() {
                node.neighbors.retain(|&nb| nb != old);
                for nb in node.neighbors.iter_mut() {
                    if *nb > old {
                        *nb -= 1;
                    }
                }
            }
            // Wähle den ähnlichsten verbleibenden Knoten als neuen Einstiegspunkt,
            // statt willkürlich Index 0 zu nehmen.
            self.entry = if self.nodes.is_empty() {
                None
            } else {
                Some(
                    self.nodes
                        .iter()
                        .enumerate()
                        .max_by(|a, b| {
                            cosine_similarity(&old_vec, &a.1.vector)
                                .partial_cmp(&cosine_similarity(&old_vec, &b.1.vector))
                                .unwrap()
                        })
                        .map(|(i, _)| i)
                        .unwrap_or(0),
                )
            };
        }

        let new_idx = self.nodes.len();

        if self.entry.is_none() {
            self.nodes.push(NswNode { id, vector, neighbors: vec![] });
            self.entry = Some(0);
            return;
        }

        let neighbors: Vec<usize> = if self.nodes.len() < 32 {
            let mut scored: Vec<(usize, f32)> = self
                .nodes
                .iter()
                .enumerate()
                .map(|(i, n)| (i, cosine_similarity(&vector, &n.vector)))
                .collect();
            scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
            scored.into_iter().take(NSW_M).map(|(i, _)| i).collect()
        } else {
            self.beam_search(&vector, NSW_M * 2)
                .into_iter()
                .take(NSW_M)
                .map(|(i, _)| i)
                .collect()
        };

        for &nb in &neighbors {
            self.nodes[nb].neighbors.push(new_idx);
            if self.nodes[nb].neighbors.len() > NSW_M {
                // Scores vorausberechnen (kein simultaner mut+imm borrow)
                let nb_vec = self.nodes[nb].vector.clone();
                let mut scored: Vec<(usize, f32)> = self.nodes[nb]
                    .neighbors
                    .iter()
                    .map(|&i| {
                        let s = if i == new_idx {
                            cosine_similarity(&nb_vec, &vector)
                        } else {
                            cosine_similarity(&nb_vec, &self.nodes[i].vector)
                        };
                        (i, s)
                    })
                    .collect();
                scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
                scored.truncate(NSW_M);
                self.nodes[nb].neighbors = scored.into_iter().map(|(i, _)| i).collect();
            }
        }

        self.nodes.push(NswNode { id, vector, neighbors });
    }

    /// Entfernt den Eintrag mit der gegebenen ID. Alle Nachbarverweise werden
    /// aktualisiert. Der Einstiegspunkt wird auf den verbleibenden Knoten mit
    /// dem niedrigsten Index gesetzt (konservative Strategie).
    pub fn remove(&mut self, id: &str) {
        if let Some(pos) = self.nodes.iter().position(|n| n.id == id) {
            self.nodes.remove(pos);
            for node in self.nodes.iter_mut() {
                node.neighbors.retain(|&nb| nb != pos);
                for nb in node.neighbors.iter_mut() {
                    if *nb > pos {
                        *nb -= 1;
                    }
                }
            }
            self.entry = if self.nodes.is_empty() { None } else { Some(0) };
        }
    }

    /// Gibt die `top_k` ähnlichsten Einträge zur `query` zurück, sortiert nach
    /// absteigender Ähnlichkeit. Bei weniger als 32 Einträgen Brute-Force,
    /// darüber NSW-Beamsuche mit `ef = max(NSW_EF, top_k * 2)`.
    pub fn search(&self, query: &[f32], top_k: usize) -> Vec<(String, f32)> {
        if self.nodes.is_empty() {
            return vec![];
        }
        if self.nodes.len() < 32 {
            let mut scored: Vec<(String, f32)> = self
                .nodes
                .iter()
                .map(|n| (n.id.clone(), cosine_similarity(&n.vector, query)))
                .collect();
            scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
            scored.truncate(top_k);
            return scored;
        }
        self.beam_search(query, NSW_EF.max(top_k * 2))
            .into_iter()
            .take(top_k)
            .map(|(idx, sim)| (self.nodes[idx].id.clone(), sim))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embed_ist_deterministisch() {
        assert_eq!(embed("hallo welt", 512), embed("hallo welt", 512));
    }

    #[test]
    fn aehnliche_texte_hoeherer_score() {
        let b = embed("gateway akzeptiert lokale datei speicher anfragen", EMBED_DIMS);
        let s = embed("gateway akzeptiert datei upload anfragen lokal", EMBED_DIMS);
        let u = embed("bananen sind tropische fruechte aus warmen klimazonen", EMBED_DIMS);
        assert!(cosine_similarity(&b, &s) > cosine_similarity(&b, &u));
    }

    #[test]
    fn subwort_trigrams_verbessern_aehnlichkeit() {
        let a = embed("speicher", EMBED_DIMS);
        let b = embed("speichern", EMBED_DIMS);
        let c = embed("banane", EMBED_DIMS);
        assert!(cosine_similarity(&a, &b) > cosine_similarity(&a, &c));
    }

    #[test]
    fn suche_findet_bestes_ergebnis() {
        let mut idx = VectorIndex::new();
        idx.insert("a", embed("rust workspace gateway storage", EMBED_DIMS));
        idx.insert("b", embed("bananen tropisch frucht warm klima", EMBED_DIMS));
        idx.insert("c", embed("gateway storage rust workspace crate tokio", EMBED_DIMS));
        let q = embed("rust gateway storage workspace", EMBED_DIMS);
        let res = idx.search(&q, 2);
        assert_eq!(res.len(), 2);
        assert!(res[0].0 == "a" || res[0].0 == "c");
        assert!(res.iter().all(|(id, _)| id != "b"));
    }

    #[test]
    fn upsert_ersetzt_bestehenden_eintrag() {
        let mut idx = VectorIndex::new();
        idx.insert("a", vec![1.0f32; EMBED_DIMS]);
        idx.insert("a", vec![0.0f32; EMBED_DIMS]);
        assert_eq!(idx.len(), 1);
    }

    #[test]
    fn nsw_skaliert_auf_100_eintraege() {
        // Semantisch diverse Texte: NSW muss klar unterschiedliche Themen trennen.
        let topics = [
            "rust async tokio gateway http server",
            "python machine learning neural network training",
            "javascript frontend react component rendering",
            "database sql query optimization index",
            "kubernetes docker container orchestration deployment",
        ];
        let mut idx = VectorIndex::new();
        for i in 0..100 {
            let topic = topics[i % topics.len()];
            idx.insert(format!("id{i}"), embed(&format!("{topic} variante {i}"), EMBED_DIMS));
        }
        // Suche nach klar rust-spezifischem Text — muss eines der Rust-Einträge finden
        let q = embed("rust async tokio gateway http server", EMBED_DIMS);
        let res = idx.search(&q, 5);
        assert!(!res.is_empty());
        // Mindestens ein Rust-Eintrag (idx 0,5,10,...) muss in Top-5 sein
        let rust_ids: Vec<&str> = res.iter().map(|(id, _)| id.as_str()).collect();
        let found_rust = rust_ids.iter().any(|id| {
            id.strip_prefix("id").and_then(|n| n.parse::<usize>().ok())
                .map(|n| n % topics.len() == 0)
                .unwrap_or(false)
        });
        assert!(found_rust, "Kein Rust-Eintrag in Top-5: {:?}", &res);
    }

    #[test]
    fn dreifach_hash_aktiviert_alle_segmente() {
        let v = embed("test eingabe dreifach hash ensemble", EMBED_DIMS);
        let t = EMBED_DIMS / 3;
        assert!(v[..t].iter().any(|x| x.abs() > 1e-6));
        assert!(v[t..2*t].iter().any(|x| x.abs() > 1e-6));
        assert!(v[2*t..].iter().any(|x| x.abs() > 1e-6));
    }
}
