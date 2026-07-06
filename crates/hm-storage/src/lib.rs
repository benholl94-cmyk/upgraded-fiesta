use std::path::{Component, Path, PathBuf};

use async_trait::async_trait;
use tokio::fs;

pub fn component_name() -> &'static str {
    "hm-storage"
}

/// Default root used when `HM_STORAGE_ROOT` is not set.
pub const DEFAULT_STORAGE_ROOT: &str = "./data/storage";

#[async_trait]
pub trait FileStorage: Send + Sync {
    async fn put(&self, key: &str, bytes: &[u8]) -> anyhow::Result<()>;
    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>>;
    async fn delete(&self, key: &str) -> anyhow::Result<()>;
    async fn exists(&self, key: &str) -> anyhow::Result<bool>;
}

/// Local-disk file storage backend. All reads/writes stay under `root`;
/// no network or external service is involved.
#[derive(Clone)]
pub struct LocalFsStorage {
    root: PathBuf,
}

impl LocalFsStorage {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    /// Builds a `LocalFsStorage` rooted at `HM_STORAGE_ROOT`, falling back to
    /// `DEFAULT_STORAGE_ROOT` when the env var is unset.
    pub fn from_env() -> Self {
        let root =
            std::env::var("HM_STORAGE_ROOT").unwrap_or_else(|_| DEFAULT_STORAGE_ROOT.to_string());
        Self::new(root)
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Resolves `key` to a path under `root`, rejecting anything that would
    /// escape it (parent segments, absolute paths, etc).
    fn resolve(&self, key: &str) -> anyhow::Result<PathBuf> {
        if key.trim().is_empty() {
            anyhow::bail!("storage key must not be empty");
        }
        let mut resolved = self.root.clone();
        for component in Path::new(key).components() {
            match component {
                Component::Normal(part) => resolved.push(part),
                _ => anyhow::bail!("storage key must be a relative path with no '..' segments"),
            }
        }
        Ok(resolved)
    }
}

#[async_trait]
impl FileStorage for LocalFsStorage {
    async fn put(&self, key: &str, bytes: &[u8]) -> anyhow::Result<()> {
        let path = self.resolve(key)?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).await?;
        }
        fs::write(path, bytes).await?;
        Ok(())
    }

    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>> {
        let path = self.resolve(key)?;
        Ok(fs::read(path).await?)
    }

    async fn delete(&self, key: &str) -> anyhow::Result<()> {
        let path = self.resolve(key)?;
        match fs::remove_file(path).await {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(error.into()),
        }
    }

    async fn exists(&self, key: &str) -> anyhow::Result<bool> {
        let path = self.resolve(key)?;
        Ok(fs::try_exists(path).await?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let path =
                std::env::temp_dir().join(format!("hm-storage-test-{}", uuid::Uuid::new_v4()));
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn temp_storage() -> (LocalFsStorage, TempDir) {
        let dir = TempDir::new();
        (LocalFsStorage::new(dir.0.clone()), dir)
    }

    #[tokio::test]
    async fn put_get_roundtrip() {
        let (storage, _dir) = temp_storage();
        storage.put("notes/hello.txt", b"hi").await.unwrap();
        assert!(storage.exists("notes/hello.txt").await.unwrap());
        assert_eq!(storage.get("notes/hello.txt").await.unwrap(), b"hi");
    }

    #[tokio::test]
    async fn delete_is_idempotent() {
        let (storage, _dir) = temp_storage();
        storage.put("a.txt", b"x").await.unwrap();
        storage.delete("a.txt").await.unwrap();
        storage.delete("a.txt").await.unwrap();
        assert!(!storage.exists("a.txt").await.unwrap());
    }

    #[tokio::test]
    async fn rejects_path_traversal() {
        let (storage, _dir) = temp_storage();
        assert!(storage.put("../escape.txt", b"x").await.is_err());
        assert!(storage.put("/etc/passwd", b"x").await.is_err());
    }
}
