//! Low-latency instrument transport for Open Lab Automation.
//!
//! The core (`conn`, `error`) is plain Rust and fully testable with `cargo test`.
//! The Python bindings are compiled only with the `python` feature (see `python.rs`).

pub mod conn;
pub mod error;

pub use conn::{Connection, Parity, SerialSettings};
pub use error::{Error, Result};

#[cfg(feature = "python")]
mod python;
