//! Python bindings (feature `python`). The GIL is released during every blocking call,
//! so a long acquisition never freezes the GUI or other measurement threads.

use std::sync::{Mutex, MutexGuard};
use std::time::Duration;

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};

use crate::conn::{Connection, Parity, SerialSettings};
use crate::error::Error;

create_exception!(ola_native, TransportError, PyException);
create_exception!(ola_native, TransportTimeout, TransportError);
create_exception!(ola_native, TransportClosed, TransportError);

fn to_py(e: Error) -> PyErr {
    let msg = e.to_string();
    match e {
        Error::Timeout => TransportTimeout::new_err(msg),
        Error::Closed => TransportClosed::new_err(msg),
        _ => TransportError::new_err(msg),
    }
}

fn ms(v: u64) -> Duration {
    Duration::from_millis(v)
}

fn opt_ms(v: Option<u64>) -> Option<Duration> {
    v.map(ms)
}

/// `bytes`-like input that also accepts `str`.
fn to_bytes(obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    if let Ok(s) = obj.cast::<PyString>() {
        return Ok(s.to_str()?.as_bytes().to_vec());
    }
    obj.extract::<Vec<u8>>()
}

fn decode(bytes: Vec<u8>) -> String {
    String::from_utf8_lossy(&bytes).into_owned()
}

#[pyclass(name = "Connection", module = "ola_native")]
struct PyConnection {
    // Mutex: PyO3 requires `Sync`, and it serialises concurrent use of one
    // connection from several Python threads (the I/O itself runs without the GIL).
    inner: Mutex<Connection>,
}

impl PyConnection {
    fn new(inner: Connection) -> Self {
        PyConnection { inner: Mutex::new(inner) }
    }

    fn conn(&self) -> MutexGuard<'_, Connection> {
        self.inner.lock().unwrap_or_else(|p| p.into_inner())
    }
}

#[pymethods]
impl PyConnection {
    #[staticmethod]
    #[pyo3(signature = (host, port=5025, timeout_ms=5000, connect_timeout_ms=3000))]
    fn open_tcp(py: Python<'_>, host: String, port: u16, timeout_ms: u64, connect_timeout_ms: u64) -> PyResult<Self> {
        let inner = py
            .detach(move || Connection::open_tcp(&host, port, ms(connect_timeout_ms), ms(timeout_ms)))
            .map_err(to_py)?;
        Ok(PyConnection::new(inner))
    }

    #[staticmethod]
    #[pyo3(signature = (path, baud=115200, timeout_ms=5000, data_bits=8, parity="N", stop_bits=1))]
    fn open_serial(
        py: Python<'_>,
        path: String,
        baud: u32,
        timeout_ms: u64,
        data_bits: u8,
        parity: &str,
        stop_bits: u8,
    ) -> PyResult<Self> {
        let parity = match parity.to_ascii_uppercase().as_str() {
            "N" => Parity::None,
            "E" => Parity::Even,
            "O" => Parity::Odd,
            other => {
                return Err(to_py(Error::InvalidArgument(format!("parity must be N, E or O, got {other:?}"))))
            }
        };
        let settings = SerialSettings { baud, data_bits, parity, stop_bits };
        let inner = py
            .detach(move || Connection::open_serial(&path, &settings, ms(timeout_ms)))
            .map_err(to_py)?;
        Ok(PyConnection::new(inner))
    }

    #[getter]
    fn peer(&self) -> String {
        self.conn().peer().to_string()
    }

    #[getter]
    fn is_open(&self) -> bool {
        self.conn().is_open()
    }

    #[getter]
    fn timeout_ms(&self) -> u64 {
        self.conn().timeout().as_millis() as u64
    }

    #[setter]
    fn set_timeout_ms(&self, value: u64) {
        self.conn().set_timeout(ms(value));
    }

    fn set_terminators(&self, write_term: &Bound<'_, PyAny>, read_term: &Bound<'_, PyAny>) -> PyResult<()> {
        let (w, r) = (to_bytes(write_term)?, to_bytes(read_term)?);
        self.conn().set_terminators(&w, &r).map_err(to_py)
    }

    fn close(&self) {
        self.conn().close();
    }

    fn write(&self, py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<()> {
        let data = to_bytes(data)?;
        py.detach(|| self.conn().write(&data)).map_err(to_py)
    }

    fn send(&self, py: Python<'_>, cmd: &Bound<'_, PyAny>) -> PyResult<()> {
        let cmd = to_bytes(cmd)?;
        py.detach(|| self.conn().send(&cmd)).map_err(to_py)
    }

    #[pyo3(signature = (cmd, timeout_ms=None))]
    fn query(&self, py: Python<'_>, cmd: &Bound<'_, PyAny>, timeout_ms: Option<u64>) -> PyResult<String> {
        let cmd = to_bytes(cmd)?;
        py.detach(|| self.conn().query(&cmd, opt_ms(timeout_ms))).map(decode).map_err(to_py)
    }

    #[pyo3(signature = (timeout_ms=None))]
    fn read_line(&self, py: Python<'_>, timeout_ms: Option<u64>) -> PyResult<String> {
        py.detach(|| self.conn().read_line(opt_ms(timeout_ms))).map(decode).map_err(to_py)
    }

    #[pyo3(signature = (term, timeout_ms=None))]
    fn read_until<'py>(
        &self,
        py: Python<'py>,
        term: &Bound<'py, PyAny>,
        timeout_ms: Option<u64>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let term = to_bytes(term)?;
        let out = py.detach(|| self.conn().read_until(&term, opt_ms(timeout_ms))).map_err(to_py)?;
        Ok(PyBytes::new(py, &out))
    }

    #[pyo3(signature = (n, timeout_ms=None))]
    fn read_exact<'py>(&self, py: Python<'py>, n: usize, timeout_ms: Option<u64>) -> PyResult<Bound<'py, PyBytes>> {
        let out = py.detach(|| self.conn().read_exact(n, opt_ms(timeout_ms))).map_err(to_py)?;
        Ok(PyBytes::new(py, &out))
    }

    #[pyo3(signature = (timeout_ms=None))]
    fn read_block<'py>(&self, py: Python<'py>, timeout_ms: Option<u64>) -> PyResult<Bound<'py, PyBytes>> {
        let out = py.detach(|| self.conn().read_block(opt_ms(timeout_ms))).map_err(to_py)?;
        Ok(PyBytes::new(py, &out))
    }

    fn flush_input(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.conn().flush_input()).map_err(to_py)
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    #[pyo3(signature = (*_args))]
    fn __exit__(&self, _args: &Bound<'_, pyo3::types::PyTuple>) {
        self.conn().close();
    }

    fn __repr__(&self) -> String {
        format!("<ola_native.Connection {} open={}>", self.conn().peer(), self.conn().is_open())
    }
}

#[pymodule]
fn ola_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyConnection>()?;
    m.add("TransportError", m.py().get_type::<TransportError>())?;
    m.add("TransportTimeout", m.py().get_type::<TransportTimeout>())?;
    m.add("TransportClosed", m.py().get_type::<TransportClosed>())?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
