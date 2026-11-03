//! Transport errors. Each variant has a stable code (`TRN-xxx`) that follows the
//! project's `[RESOURCE-XXX]` convention (see ERROR_CODES.md).

use std::fmt;
use std::io;

/// Everything that can go wrong in the transport. Each variant has a stable `TRN-xxx` code.
#[derive(Debug)]
pub enum Error {
    /// Could not open the connection (TRN-001).
    Connect(String),
    /// I/O failure on an open connection (TRN-002).
    Io(io::Error),
    /// No (complete) answer within the timeout (TRN-003).
    Timeout,
    /// The connection is closed, locally or by the peer (TRN-004).
    Closed,
    /// The peer sent something that violates the expected framing (TRN-005).
    Protocol(String),
    /// Invalid argument from the caller (TRN-006).
    InvalidArgument(String),
}

/// Result of every transport operation.
pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    /// Stable error code (`TRN-001`..`TRN-006`), documented in `ERROR_CODES.md`.
    pub fn code(&self) -> &'static str {
        match self {
            Error::Connect(_) => "TRN-001",
            Error::Io(_) => "TRN-002",
            Error::Timeout => "TRN-003",
            Error::Closed => "TRN-004",
            Error::Protocol(_) => "TRN-005",
            Error::InvalidArgument(_) => "TRN-006",
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Connect(m) => write!(f, "[{}] connection failed: {}", self.code(), m),
            Error::Io(e) => write!(f, "[{}] I/O error: {}", self.code(), e),
            Error::Timeout => write!(f, "[{}] timeout waiting for the instrument", self.code()),
            Error::Closed => write!(f, "[{}] connection closed", self.code()),
            Error::Protocol(m) => write!(f, "[{}] protocol error: {}", self.code(), m),
            Error::InvalidArgument(m) => write!(f, "[{}] invalid argument: {}", self.code(), m),
        }
    }
}

impl std::error::Error for Error {}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Io(e)
    }
}
