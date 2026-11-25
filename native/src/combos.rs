// Copyright (C) 2025-2026 Erik Medeossi
// This file is part of Open Lab Automation.
// Licensed under the GNU General Public License v3.0; see the LICENSE file.

//! Combinations of resistors (series / parallel, nested) for a list of target currents.
//!
//! A kit of `n` resistors has far too many networks to list one by one (they grow like `3^n`),
//! so the search goes **by the number of resistors used** and keeps, for every value (grouped in
//! narrow bands of relative width `eps`), only a few ways to make it, each with the set of
//! physical resistors it uses; two pieces are joined only if they use different resistors. The
//! power in every resistor is tracked as a fraction of its rating per volt squared, so that a
//! network whose resistor would exceed `margin` of its rating at the output voltage is left out.
//!
//! The plan then picks, for every target current, among the nearest networks the path that costs
//! least, where the cost of a point is `w_dev` times its distance from the target (in steps) plus
//! the number of physical resistors that must be moved from the previous point. The result does
//! not depend on anything random: the same input gives the same plan, whatever the platform
//! (the Python version in `ola/combinations.py` does exactly the same steps).

use std::collections::HashMap;
use std::sync::Arc;

/// One physical resistor of the kit.
#[derive(Clone, Copy, Debug)]
pub struct Resistor {
    /// Resistance in ohms (above 0).
    pub ohms: f64,
    /// Power rating in watts (`f64::INFINITY` when it is not known: not checked).
    pub watts: f64,
}

/// How the resistors of a network are joined.
#[derive(Debug)]
pub enum Node {
    /// One resistor, by its position in the kit.
    Leaf(usize),
    /// Two sub-networks in series.
    Series(Arc<Node>, Arc<Node>),
    /// Two sub-networks in parallel.
    Parallel(Arc<Node>, Arc<Node>),
}

impl Node {
    /// The network as JSON text: a number for a resistor, `["s", a, b]` / `["p", a, b]`.
    pub fn to_json(&self) -> String {
        match self {
            Node::Leaf(i) => i.to_string(),
            Node::Series(a, b) => format!("[\"s\",{},{}]", a.to_json(), b.to_json()),
            Node::Parallel(a, b) => format!("[\"p\",{},{}]", a.to_json(), b.to_json()),
        }
    }
}

#[derive(Clone)]
struct Way {
    ohms: f64,
    mask: u64,
    /// Fraction of the rating of the most loaded resistor, per volt squared across the network.
    q: f64,
    tree: Arc<Node>,
}

/// What to compute.
#[derive(Clone, Debug)]
pub struct Params {
    /// Output voltage of the converter (V).
    pub vout: f64,
    /// The output voltage at each target current (V), when it is not the same for all (a converter
    /// that is not regulated, once its curve is known); empty: `vout` for every target.
    pub vouts: Vec<f64>,
    /// Distance between two targets (A): the unit of the deviation in the cost.
    pub step: f64,
    /// Relative width of a band of values (0.01 = 1 %).
    pub eps: f64,
    /// Ways kept for each band of values.
    pub ways: usize,
    /// Nearest networks considered for each target.
    pub candidates: usize,
    /// Weight of the deviation from the target, in steps.
    pub w_dev: f64,
    /// Weight of each resistor moved from the previous point.
    pub w_change: f64,
    /// Largest fraction of its rating a resistor may carry (0.8 = 80 %).
    pub margin: f64,
}

impl Default for Params {
    fn default() -> Self {
        Params {
            vout: 1.0,
            vouts: Vec::new(),
            step: 1.0,
            eps: 0.01,
            ways: 3,
            candidates: 6,
            w_dev: 10.0,
            w_change: 1.0,
            margin: 0.8,
        }
    }
}

/// One planned point.
#[derive(Debug)]
pub struct Point {
    /// The current that was asked for (A).
    pub target: f64,
    /// Resistance of the network (ohm).
    pub ohms: f64,
    /// Current it gives at the output voltage (A).
    pub current: f64,
    /// Fraction of its rating carried by the most loaded resistor at the output voltage.
    pub load: f64,
    /// Resistors moved from the previous point (the first point counts all of its own).
    pub changes: u32,
    /// How the resistors are joined.
    pub tree: Arc<Node>,
}

fn positive(x: f64) -> bool {
    x > 0.0 // false for NaN as well
}

/// Round half away from zero, as Python's version does it.
fn band(value: f64, lg: f64) -> i64 {
    let x = value.ln() / lg;
    (x.abs() + 0.5).floor().copysign(x) as i64
}

fn ordered(level: &HashMap<i64, Vec<Way>>) -> Vec<Way> {
    let mut keys: Vec<i64> = level.keys().copied().collect();
    keys.sort_unstable();
    keys.into_iter()
        .flat_map(|k| level[&k].iter().cloned())
        .collect()
}

/// Keep a way if its band has room, or it is better (a lower load) than the worst kept; the
/// tree is only built then, because most candidates are not kept.
fn insert(
    out: &mut HashMap<i64, Vec<Way>>,
    key: i64,
    (ohms, mask, q): (f64, u64, f64),
    keep: usize,
    tree: impl FnOnce() -> Arc<Node>,
) {
    let slot = out.entry(key).or_default();
    if slot.iter().any(|w| w.mask == mask) {
        return;
    }
    if slot.len() < keep {
        slot.push(Way {
            ohms,
            mask,
            q,
            tree: tree(),
        });
        return;
    }
    let mut worst = 0;
    for (i, w) in slot.iter().enumerate() {
        if w.q > slot[worst].q {
            worst = i;
        }
    }
    if q < slot[worst].q {
        slot[worst] = Way {
            ohms,
            mask,
            q,
            tree: tree(),
        };
    }
}

fn search(resistors: &[Resistor], eps: f64, keep: usize) -> Vec<Vec<Way>> {
    let n = resistors.len();
    let lg = eps.ln_1p();
    let mut levels: Vec<HashMap<i64, Vec<Way>>> = vec![HashMap::new(); n + 1];
    for (i, r) in resistors.iter().enumerate() {
        let way = (r.ohms, 1u64 << i, 1.0 / (r.ohms * r.watts));
        insert(&mut levels[1], band(r.ohms, lg), way, keep, || {
            Arc::new(Node::Leaf(i))
        });
    }
    for l in 2..=n {
        let mut out: HashMap<i64, Vec<Way>> = HashMap::new();
        for i in 1..=l / 2 {
            let (left, right) = (ordered(&levels[i]), ordered(&levels[l - i]));
            for x in &left {
                for y in &right {
                    if x.mask & y.mask != 0 {
                        continue;
                    }
                    let mask = x.mask | y.mask;
                    let total = x.ohms + y.ohms;
                    let (fx, fy) = (x.ohms / total, y.ohms / total);
                    let q = (x.q * (fx * fx)).max(y.q * (fy * fy));
                    insert(&mut out, band(total, lg), (total, mask, q), keep, || {
                        Arc::new(Node::Series(x.tree.clone(), y.tree.clone()))
                    });
                    let both = x.ohms * y.ohms / total;
                    insert(
                        &mut out,
                        band(both, lg),
                        (both, mask, x.q.max(y.q)),
                        keep,
                        || Arc::new(Node::Parallel(x.tree.clone(), y.tree.clone())),
                    );
                }
            }
        }
        levels[l] = out;
    }
    levels.into_iter().skip(1).map(|lv| ordered(&lv)).collect()
}

/// Plan the networks for the target currents (all above 0, in the order they will be measured).
///
/// Returns an empty list for no targets, and an error text for a value that cannot be used
/// (a resistor of 0 ohm or less, more than 64 resistors, an output voltage that is not above 0).
pub fn plan(resistors: &[Resistor], targets: &[f64], p: &Params) -> Result<Vec<Point>, String> {
    if resistors.is_empty() || resistors.len() > 64 {
        return Err("the kit needs from 1 to 64 resistors".into());
    }
    if resistors
        .iter()
        .any(|r| !positive(r.ohms) || !positive(r.watts))
    {
        return Err("every resistor needs a resistance and a rating above 0".into());
    }
    if ![p.vout, p.step, p.eps].into_iter().all(positive) || p.ways == 0 || p.candidates == 0 {
        return Err("the output voltage, step and resolution must be above 0".into());
    }
    if !targets.iter().copied().all(positive) {
        return Err("every target current must be above 0".into());
    }
    if !p.vouts.is_empty()
        && (p.vouts.len() != targets.len() || !p.vouts.iter().copied().all(positive))
    {
        return Err("give one output voltage above 0 for every target".into());
    }
    if targets.is_empty() {
        return Ok(Vec::new());
    }
    let volts: Vec<f64> = if p.vouts.is_empty() {
        vec![p.vout; targets.len()]
    } else {
        p.vouts.clone()
    };
    let found: Vec<Way> = search(resistors, p.eps, p.ways)
        .into_iter()
        .flatten()
        .collect();
    // the nearest networks to every target that keep every resistor within its rating at the
    // voltage of that target, then the cheapest path through them
    let mut layers: Vec<Vec<&Way>> = Vec::with_capacity(targets.len());
    for (t, v) in targets.iter().zip(&volts) {
        let mut near: Vec<&Way> = found.iter().filter(|w| w.q * v * v <= p.margin).collect();
        if near.is_empty() {
            return Err(format!(
                "no combination of the kit keeps every resistor within its rating at {v} V"
            ));
        }
        near.sort_by(|a, b| {
            (v / a.ohms - t)
                .abs()
                .partial_cmp(&(v / b.ohms - t).abs())
                .unwrap()
        });
        near.truncate(p.candidates);
        layers.push(near);
    }
    let mut cost: Vec<Vec<(f64, usize)>> = Vec::new();
    for (li, layer) in layers.iter().enumerate() {
        let mut row = Vec::with_capacity(layer.len());
        for w in layer {
            let dev = (volts[li] / w.ohms - targets[li]).abs() / p.step;
            let mut best = (f64::MAX, 0usize);
            if li == 0 {
                best = (p.w_dev * dev + p.w_change * w.mask.count_ones() as f64, 0);
            } else {
                for (pi, prev) in layers[li - 1].iter().enumerate() {
                    let moved = (prev.mask ^ w.mask).count_ones() as f64;
                    let c = cost[li - 1][pi].0 + p.w_dev * dev + p.w_change * moved;
                    if c < best.0 {
                        best = (c, pi);
                    }
                }
            }
            row.push(best);
        }
        cost.push(row);
    }
    let mut at = 0;
    for (i, c) in cost[cost.len() - 1].iter().enumerate() {
        if c.0 < cost[cost.len() - 1][at].0 {
            at = i;
        }
    }
    let mut chosen = vec![0usize; layers.len()];
    for li in (0..layers.len()).rev() {
        chosen[li] = at;
        at = cost[li][at].1;
    }
    let mut points = Vec::with_capacity(layers.len());
    let mut before = 0u64;
    for (li, layer) in layers.iter().enumerate() {
        let w = layer[chosen[li]];
        points.push(Point {
            target: targets[li],
            ohms: w.ohms,
            current: volts[li] / w.ohms,
            load: w.q * volts[li] * volts[li],
            changes: (before ^ w.mask).count_ones(),
            tree: w.tree.clone(),
        });
        before = w.mask;
    }
    Ok(points)
}
