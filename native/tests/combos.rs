// Copyright (C) 2025-2026 Erik Medeossi
// This file is part of Open Lab Automation.
// Licensed under the GNU General Public License v3.0; see the LICENSE file.

use ola_native::combos::{plan, Params, Resistor};

fn kit(values: &[f64], watts: f64) -> Vec<Resistor> {
    values
        .iter()
        .map(|&ohms| Resistor { ohms, watts })
        .collect()
}

fn example() -> (Vec<Resistor>, Vec<f64>, Params) {
    let params = Params {
        vout: 12.0,
        step: 1.0,
        margin: 1.0,
        ..Params::default()
    };
    let kit = kit(&[12.0, 10.0, 5.0, 2.0, 1.0, 12.0, 5.0], 100.0);
    (kit, (1..=10).map(f64::from).collect(), params)
}

#[test]
fn the_example_kit_reaches_every_current() {
    let (kit, targets, params) = example();
    let points = plan(&kit, &targets, &params).unwrap();
    assert_eq!(points.len(), 10);
    for p in &points {
        assert!(
            (p.current - p.target).abs() < 0.05 * params.step * 1.0 + 0.03,
            "{p:?}"
        );
        assert!(p.load <= 1.0);
    }
    assert!((points[0].ohms - 12.0).abs() < 1e-9); // 1 A at 12 V is the 12 ohm resistor alone
    assert!((points[9].ohms - 1.2).abs() < 0.02); // 10 A
}

#[test]
fn a_resistor_over_its_rating_is_not_used() {
    // the 1 ohm resistor alone would carry 144 W at 12 V: only 100 W allowed
    let (kit, _, params) = example();
    let points = plan(&kit, &[12.0], &params).unwrap();
    assert!(points[0].tree.to_json() != "4", "{:?}", points[0]);
    assert!(points[0].load <= 1.0);
}

#[test]
fn the_same_input_gives_the_same_plan() {
    let (kit, targets, params) = example();
    let a = plan(&kit, &targets, &params).unwrap();
    let b = plan(&kit, &targets, &params).unwrap();
    let text = |v: &[ola_native::combos::Point]| {
        v.iter()
            .map(|p| format!("{}:{}", p.ohms, p.tree.to_json()))
            .collect::<Vec<_>>()
    };
    assert_eq!(text(&a), text(&b));
}

#[test]
fn bad_values_are_refused() {
    let (kit, targets, params) = example();
    assert!(plan(&[], &targets, &params).is_err());
    assert!(plan(&kit, &[0.0], &params).is_err());
    assert!(plan(&kit, &[-1.0], &params).is_err());
    assert!(plan(
        &kit,
        &targets,
        &Params {
            vout: 0.0,
            ..params.clone()
        }
    )
    .is_err());
    assert!(plan(&kit, &[], &params).unwrap().is_empty());
}

#[test]
fn a_big_kit_is_fast() {
    let values: Vec<f64> = (0..20).map(|i| 1.0 + i as f64 * 1.7).collect();
    let started = std::time::Instant::now();
    let params = Params {
        vout: 12.0,
        step: 0.5,
        margin: 1.0,
        ..Params::default()
    };
    let points = plan(&kit(&values, 100.0), &[1.0, 2.0, 3.0, 4.0], &params).unwrap();
    assert_eq!(points.len(), 4);
    assert!(started.elapsed().as_secs() < 30);
}
