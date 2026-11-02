use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;
use std::time::{Duration, Instant};

use ola_native::{Connection, Error};

/// Start a one-connection fake instrument; `handler` owns the accepted socket.
fn fake<F>(handler: F) -> u16
where
    F: FnOnce(TcpStream) + Send + 'static,
{
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    thread::spawn(move || {
        let (s, _) = listener.accept().unwrap();
        s.set_nodelay(true).unwrap();
        handler(s);
    });
    port
}

fn open(port: u16) -> Connection {
    Connection::open_tcp("127.0.0.1", port, Duration::from_secs(2), Duration::from_millis(500)).unwrap()
}

/// Reads newline-terminated commands; answers every "...?" with `reply`.
fn echo_server(mut s: TcpStream, reply: &'static [u8]) {
    let mut acc = Vec::new();
    let mut buf = [0u8; 1024];
    loop {
        let n = match s.read(&mut buf) {
            Ok(0) | Err(_) => return,
            Ok(n) => n,
        };
        acc.extend_from_slice(&buf[..n]);
        while let Some(p) = acc.iter().position(|&b| b == b'\n') {
            let line: Vec<u8> = acc.drain(..=p).collect();
            if line.ends_with(b"?\n") {
                s.write_all(reply).unwrap();
            }
        }
    }
}

#[test]
fn query_roundtrip() {
    let port = fake(|s| echo_server(s, b"1.234567\n"));
    let mut c = open(port);
    assert_eq!(c.query(b"MEAS:VOLT?", None).unwrap(), b"1.234567");
    assert_eq!(c.query(b"MEAS:CURR?", None).unwrap(), b"1.234567");
}

#[test]
fn crlf_is_stripped() {
    let port = fake(|s| echo_server(s, b"ABC\r\n"));
    let mut c = open(port);
    assert_eq!(c.query(b"*IDN?", None).unwrap(), b"ABC");
}

#[test]
fn latency_regression_no_nagle_delay() {
    // Regression for PLAN.md §4.1: the old backend took ~44 ms per query.
    let port = fake(|s| echo_server(s, b"1.0\n"));
    let mut c = open(port);
    let mut times = Vec::new();
    for _ in 0..100 {
        let t = Instant::now();
        c.query(b"MEAS:VOLT?", None).unwrap();
        times.push(t.elapsed());
    }
    times.sort();
    let median = times[times.len() / 2];
    assert!(median < Duration::from_millis(5), "median query latency {median:?} is too high");
}

#[test]
fn timeout_when_no_answer() {
    let port = fake(|s| {
        let _s = s;
        thread::sleep(Duration::from_secs(2));
    });
    let mut c = open(port);
    let t = Instant::now();
    let err = c.query(b"MEAS:VOLT?", Some(Duration::from_millis(100))).unwrap_err();
    assert!(matches!(err, Error::Timeout), "{err:?}");
    assert!(t.elapsed() < Duration::from_millis(400));
}

#[test]
fn answer_split_across_segments() {
    let port = fake(|mut s| {
        let mut buf = [0u8; 64];
        let _ = s.read(&mut buf);
        for part in [&b"1.2"[..], &b"34"[..], &b"5\n"[..]] {
            s.write_all(part).unwrap();
            s.flush().unwrap();
            thread::sleep(Duration::from_millis(20));
        }
    });
    let mut c = open(port);
    assert_eq!(c.query(b"X?", None).unwrap(), b"1.2345");
}

#[test]
fn two_answers_in_one_segment() {
    let port = fake(|mut s| {
        let mut buf = [0u8; 64];
        let _ = s.read(&mut buf);
        s.write_all(b"one\ntwo\n").unwrap();
        thread::sleep(Duration::from_millis(200));
    });
    let mut c = open(port);
    c.send(b"X?").unwrap();
    assert_eq!(c.read_line(None).unwrap(), b"one");
    assert_eq!(c.read_line(None).unwrap(), b"two");
}

#[test]
fn ieee_block_split_and_terminator_dropped() {
    let payload: Vec<u8> = (0..=255u8).cycle().take(5000).collect();
    let p2 = payload.clone();
    let port = fake(move |mut s| {
        let mut buf = [0u8; 64];
        let _ = s.read(&mut buf);
        let mut msg = format!("#4{:04}", p2.len()).into_bytes();
        msg.extend_from_slice(&p2);
        msg.push(b'\n');
        msg.extend_from_slice(b"next\n");
        // deliver in awkward chunks
        for chunk in msg.chunks(777) {
            s.write_all(chunk).unwrap();
            s.flush().unwrap();
            thread::sleep(Duration::from_millis(2));
        }
        thread::sleep(Duration::from_millis(300));
    });
    let mut c = open(port);
    c.send(b"CURV?").unwrap();
    assert_eq!(c.read_block(None).unwrap(), payload);
    // the block's trailing "\n" must not leak into the next read
    assert_eq!(c.read_line(None).unwrap(), b"next");
}

#[test]
fn block_with_bad_header_is_protocol_error() {
    let port = fake(|mut s| {
        let mut buf = [0u8; 64];
        let _ = s.read(&mut buf);
        s.write_all(b"oops\n").unwrap();
        thread::sleep(Duration::from_millis(200));
    });
    let mut c = open(port);
    c.send(b"CURV?").unwrap();
    assert!(matches!(c.read_block(None).unwrap_err(), Error::Protocol(_)));
}

#[test]
fn read_exact_and_custom_terminator() {
    let port = fake(|mut s| {
        let mut buf = [0u8; 64];
        let _ = s.read(&mut buf);
        s.write_all(b"ab>>cd").unwrap();
        thread::sleep(Duration::from_millis(200));
    });
    let mut c = open(port);
    c.set_terminators(b"\r", b">>").unwrap();
    c.send(b"X").unwrap();
    assert_eq!(c.read_line(None).unwrap(), b"ab");
    assert_eq!(c.read_exact(2, None).unwrap(), b"cd");
}

#[test]
fn peer_close_is_reported() {
    let port = fake(|s| drop(s));
    let mut c = open(port);
    thread::sleep(Duration::from_millis(50));
    let err = c.read_line(Some(Duration::from_millis(300))).unwrap_err();
    assert!(matches!(err, Error::Closed), "{err:?}");
    assert!(!c.is_open());
}

#[test]
fn flush_input_discards_stale_data() {
    let port = fake(|mut s| {
        s.write_all(b"stale\n").unwrap();
        let mut buf = [0u8; 64];
        let _ = s.read(&mut buf);
        s.write_all(b"fresh\n").unwrap();
        thread::sleep(Duration::from_millis(200));
    });
    let mut c = open(port);
    thread::sleep(Duration::from_millis(50));
    c.flush_input().unwrap();
    assert_eq!(c.query(b"X?", None).unwrap(), b"fresh");
}

#[test]
fn connect_refused_is_connect_error() {
    // bind then drop to get a free port nobody listens on
    let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
    let err = Connection::open_tcp("127.0.0.1", port, Duration::from_millis(500), Duration::from_millis(100))
        .err()
        .unwrap();
    assert!(matches!(err, Error::Connect(_)), "{err:?}");
}

#[test]
fn operations_after_close_fail() {
    let port = fake(|s| echo_server(s, b"1\n"));
    let mut c = open(port);
    c.close();
    assert!(matches!(c.send(b"X?").unwrap_err(), Error::Closed));
}
