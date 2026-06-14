//! Heavy Metal / UniqueClaw SDK compatibility target.
//!
//! This library target exists so Cargo recognizes `crates/hm-sdk` as a valid
//! workspace member. It intentionally keeps the public surface small until the
//! plugin API is expanded.

#[derive(Debug, Clone)]
pub struct HmSdkManifest {
    pub name: String,
    pub version: String,
    pub capabilities: Vec<String>,
}

pub trait HmPlugin {
    fn manifest(&self) -> HmSdkManifest;
}

pub mod prelude {
    pub use crate::{HmPlugin, HmSdkManifest};
}
