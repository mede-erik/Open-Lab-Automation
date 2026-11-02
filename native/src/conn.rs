//! A byte-stream connection to an instrument (TCP/LXI or serial).
//!
//! Latency rules enforced here (see PLAN.md §4.1):
//! * TCP_NODELAY is always on;
//! * a command and its terminator go out in **one** write;
//! * reads are buffered and bounded by a per-call deadline.

use std::io::{self, ErrorKind, Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

use crate::error::{Error, Result};

const READ_CHUNK: usize = 16 * 1024;
/// Upper bound for a single response, to stop a misbehaving peer from exhausting memory.
pub const MAX_RESPONSE: usize = 256 * 1024 * 1024;

enum Link {
    Tcp(TcpStream),
    Serial(Box<dyn serialport::SerialPort>),
}

impl Link {
    fn set_timeout(&mut self, d: Duration) -> io::Result<()> {
        match self {
            Link::Tcp(s) => s.set_read_timeout(Some(d)),
            Link::Serial(p) => p.set_timeout(d).map_err(io::Error::from),
        }
    }

    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        match self {
            Link::Tcp(s) => s.read(buf),
            Link::Serial(p) => p.read(buf),
        }
    }

    fn write_all(&mut self, data: &[u8]) -> io::Result<()> {
        match self {
            Link::Tcp(s) => s.write_all(data).and_then(|_| s.flush()),
            Link::Serial(p) => p.write_all(data).and_then(|_| p.flush()),
        }
    }

    fn is_tcp(&self) -> bool {
        matches!(self, Link::Tcp(_))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Parity {
    None,
    Even,
    Odd,
}

#[derive(Debug, Clone)]
pub struct SerialSettings {
    pub baud: u32,
    pub data_bits: u8,
    pub parity: Parity,
    pub stop_bits: u8,
}

impl Default for SerialSettings {
    fn default() -> Self {
        SerialSettings { baud: 115_200, data_bits: 8, parity: Parity::None, stop_bits: 1 }
    }
}

pub struct Connection {
    link: Option<Link>,
    rbuf: Vec<u8>,
    write_term: Vec<u8>,
    read_term: Vec<u8>,
    timeout: Duration,
    /// After a binary block the instrument usually appends a terminator; it is dropped
    /// lazily the next time data is read.
    pending_term: bool,
    peer: String,
}

impl Connection {
    // ----- construction -------------------------------------------------------------

    pub fn open_tcp(host: &str, port: u16, connect_timeout: Duration, io_timeout: Duration) -> Result<Self> {
        let addrs = (host, port)
            .to_socket_addrs()
            .map_err(|e| Error::Connect(format!("{host}:{port}: {e}")))?;
        let mut last: Option<io::Error> = None;
        for addr in addrs {
            match TcpStream::connect_timeout(&addr, connect_timeout) {
                Ok(stream) => {
                    stream.set_nodelay(true)?;
                    stream.set_write_timeout(Some(io_timeout.max(Duration::from_millis(1))))?;
                    return Ok(Self::new(Link::Tcp(stream), format!("tcp://{host}:{port}"), io_timeout));
                }
                Err(e) => last = Some(e),
            }
        }
        Err(Error::Connect(match last {
            Some(e) => format!("{host}:{port}: {e}"),
            None => format!("{host}:{port}: no address resolved"),
        }))
    }

    pub fn open_serial(path: &str, settings: &SerialSettings, io_timeout: Duration) -> Result<Self> {
        use serialport::{DataBits, Parity as P, StopBits};
        let data_bits = match settings.data_bits {
            5 => DataBits::Five,
            6 => DataBits::Six,
            7 => DataBits::Seven,
            8 => DataBits::Eight,
            n => return Err(Error::InvalidArgument(format!("data_bits must be 5..8, got {n}"))),
        };
        let stop_bits = match settings.stop_bits {
            1 => StopBits::One,
            2 => StopBits::Two,
            n => return Err(Error::InvalidArgument(format!("stop_bits must be 1 or 2, got {n}"))),
        };
        let parity = match settings.parity {
            Parity::None => P::None,
            Parity::Even => P::Even,
            Parity::Odd => P::Odd,
        };
        let port = serialport::new(path, settings.baud)
            .data_bits(data_bits)
            .stop_bits(stop_bits)
            .parity(parity)
            .timeout(io_timeout.max(Duration::from_millis(1)))
            .open()
            .map_err(|e| Error::Connect(format!("{path}: {e}")))?;
        Ok(Self::new(Link::Serial(port), format!("serial://{path}"), io_timeout))
    }

    fn new(link: Link, peer: String, timeout: Duration) -> Self {
        Connection {
            link: Some(link),
            rbuf: Vec::with_capacity(READ_CHUNK),
            write_term: b"\n".to_vec(),
            read_term: b"\n".to_vec(),
            timeout,
            pending_term: false,
            peer,
        }
    }

    // ----- settings -----------------------------------------------------------------

    pub fn peer(&self) -> &str {
        &self.peer
    }

    pub fn is_open(&self) -> bool {
        self.link.is_some()
    }

    pub fn timeout(&self) -> Duration {
        self.timeout
    }

    pub fn set_timeout(&mut self, timeout: Duration) {
        self.timeout = timeout;
    }

    pub fn set_terminators(&mut self, write_term: &[u8], read_term: &[u8]) -> Result<()> {
        if read_term.is_empty() {
            return Err(Error::InvalidArgument("read terminator must not be empty".into()));
        }
        self.write_term = write_term.to_vec();
        self.read_term = read_term.to_vec();
        Ok(())
    }

    pub fn close(&mut self) {
        self.link = None;
        self.rbuf.clear();
        self.pending_term = false;
    }

    // ----- writing ------------------------------------------------------------------

    /// Write raw bytes, exactly as given, in a single write.
    pub fn write(&mut self, data: &[u8]) -> Result<()> {
        let link = self.link.as_mut().ok_or(Error::Closed)?;
        link.write_all(data).map_err(|e| self.map_io(e))
    }

    /// Send a command followed by the write terminator, in a **single** write.
    pub fn send(&mut self, cmd: &[u8]) -> Result<()> {
        let mut buf = Vec::with_capacity(cmd.len() + self.write_term.len());
        buf.extend_from_slice(cmd);
        buf.extend_from_slice(&self.write_term);
        self.write(&buf)
    }

    // ----- reading ------------------------------------------------------------------

    /// Drop everything received but not yet consumed (stale answers), including
    /// bytes already waiting in the OS buffer.
    pub fn flush_input(&mut self) -> Result<()> {
        self.rbuf.clear();
        self.pending_term = false;
        let link = self.link.as_mut().ok_or(Error::Closed)?;
        let mut tmp = [0u8; 4096];
        loop {
            if link.set_timeout(Duration::from_millis(1)).is_err() {
                break;
            }
            match link.read(&mut tmp) {
                Ok(0) | Err(_) => break,
                Ok(_) => continue,
            }
        }
        Ok(())
    }

    /// Read up to (and consuming) `term`; the terminator is not returned.
    pub fn read_until(&mut self, term: &[u8], timeout: Option<Duration>) -> Result<Vec<u8>> {
        if term.is_empty() {
            return Err(Error::InvalidArgument("terminator must not be empty".into()));
        }
        let deadline = Instant::now() + timeout.unwrap_or(self.timeout);
        self.strip_pending();
        let mut scanned = 0usize;
        loop {
            if let Some(pos) = find(&self.rbuf, term, scanned) {
                let mut line: Vec<u8> = self.rbuf.drain(..pos + term.len()).collect();
                line.truncate(pos);
                return Ok(line);
            }
            scanned = self.rbuf.len().saturating_sub(term.len() - 1);
            self.fill(deadline)?;
            self.strip_pending();
        }
    }

    /// Read one line using the read terminator. A trailing `\r` before `\n` is removed.
    pub fn read_line(&mut self, timeout: Option<Duration>) -> Result<Vec<u8>> {
        let term = self.read_term.clone();
        let mut line = self.read_until(&term, timeout)?;
        if term == b"\n" && line.last() == Some(&b'\r') {
            line.pop();
        }
        Ok(line)
    }

    /// Send a command and read one line back.
    pub fn query(&mut self, cmd: &[u8], timeout: Option<Duration>) -> Result<Vec<u8>> {
        self.send(cmd)?;
        self.read_line(timeout)
    }

    /// Read exactly `n` bytes.
    pub fn read_exact(&mut self, n: usize, timeout: Option<Duration>) -> Result<Vec<u8>> {
        if n > MAX_RESPONSE {
            return Err(Error::InvalidArgument(format!("{n} bytes exceeds the limit")));
        }
        let deadline = Instant::now() + timeout.unwrap_or(self.timeout);
        self.strip_pending();
        self.ensure(n, deadline)?;
        Ok(self.rbuf.drain(..n).collect())
    }

    /// Read an IEEE 488.2 definite-length block (`#<d><len><data>`), e.g. a waveform.
    pub fn read_block(&mut self, timeout: Option<Duration>) -> Result<Vec<u8>> {
        let deadline = Instant::now() + timeout.unwrap_or(self.timeout);
        self.strip_pending();
        self.ensure(2, deadline)?;
        if self.rbuf[0] != b'#' {
            return Err(Error::Protocol(format!(
                "block header must start with '#', got 0x{:02x}",
                self.rbuf[0]
            )));
        }
        let digits = match self.rbuf[1] {
            b'1'..=b'9' => (self.rbuf[1] - b'0') as usize,
            b'0' => return Err(Error::Protocol("indefinite-length blocks (#0) are not supported".into())),
            c => return Err(Error::Protocol(format!("bad block length digit count 0x{c:02x}"))),
        };
        self.ensure(2 + digits, deadline)?;
        let len: usize = std::str::from_utf8(&self.rbuf[2..2 + digits])
            .ok()
            .and_then(|s| s.parse().ok())
            .ok_or_else(|| Error::Protocol("non-numeric block length".into()))?;
        if len > MAX_RESPONSE {
            return Err(Error::Protocol(format!("block of {len} bytes exceeds the limit")));
        }
        self.ensure(2 + digits + len, deadline)?;
        let data: Vec<u8> = self.rbuf[2 + digits..2 + digits + len].to_vec();
        self.rbuf.drain(..2 + digits + len);
        self.pending_term = true;
        self.strip_pending();
        Ok(data)
    }

    // ----- internals ----------------------------------------------------------------

    fn ensure(&mut self, n: usize, deadline: Instant) -> Result<()> {
        while self.rbuf.len() < n {
            self.fill(deadline)?;
            self.strip_pending();
        }
        Ok(())
    }

    fn strip_pending(&mut self) {
        if !self.pending_term {
            return;
        }
        if self.rbuf.starts_with(&self.read_term) {
            self.rbuf.drain(..self.read_term.len());
            self.pending_term = false;
        } else if !self.rbuf.is_empty() && !self.read_term.starts_with(&self.rbuf) {
            // data that is not the terminator: the instrument did not send one
            self.pending_term = false;
        }
    }

    fn fill(&mut self, deadline: Instant) -> Result<()> {
        if self.rbuf.len() >= MAX_RESPONSE {
            return Err(Error::Protocol("response exceeds the size limit".into()));
        }
        loop {
            let now = Instant::now();
            if now >= deadline {
                return Err(Error::Timeout);
            }
            let remaining = (deadline - now).max(Duration::from_millis(1));
            let link = self.link.as_mut().ok_or(Error::Closed)?;
            link.set_timeout(remaining)?;
            let start = self.rbuf.len();
            self.rbuf.resize(start + READ_CHUNK, 0);
            let res = link.read(&mut self.rbuf[start..]);
            match res {
                Ok(0) => {
                    self.rbuf.truncate(start);
                    if link.is_tcp() {
                        self.link = None;
                        return Err(Error::Closed);
                    }
                    continue;
                }
                Ok(n) => {
                    self.rbuf.truncate(start + n);
                    return Ok(());
                }
                Err(e) => {
                    self.rbuf.truncate(start);
                    match e.kind() {
                        ErrorKind::Interrupted => continue,
                        ErrorKind::WouldBlock | ErrorKind::TimedOut => return Err(Error::Timeout),
                        _ => return Err(self.map_io(e)),
                    }
                }
            }
        }
    }

    fn map_io(&mut self, e: io::Error) -> Error {
        match e.kind() {
            ErrorKind::WouldBlock | ErrorKind::TimedOut => Error::Timeout,
            ErrorKind::BrokenPipe
            | ErrorKind::ConnectionReset
            | ErrorKind::ConnectionAborted
            | ErrorKind::UnexpectedEof => {
                self.link = None;
                Error::Closed
            }
            _ => Error::Io(e),
        }
    }
}

fn find(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    if hay.len() < needle.len() || from > hay.len() - needle.len() {
        return None;
    }
    hay[from..].windows(needle.len()).position(|w| w == needle).map(|p| p + from)
}
