mod instrument_library;

use instrument_library::InstrumentLibrary;
use serde_json::to_string_pretty;
use std::path::PathBuf;

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        return Err(usage());
    }

    let library_path = default_library_path()?;
    let library = InstrumentLibrary::load_from_file(library_path)?;

    match args[1].as_str() {
        "types" => {
            println!("{}", library.get_all_types().join("\n"));
        }
        "series" => {
            if args.len() != 3 {
                return Err(usage());
            }
            let series = library
                .get_series(&args[2])
                .ok_or_else(|| "Series not found".to_string())?;
            println!("{}", to_string_pretty(series).map_err(|e| e.to_string())?);
        }
        "models" => {
            if args.len() != 4 {
                return Err(usage());
            }
            let models = library
                .get_models(&args[2], &args[3])
                .ok_or_else(|| "Models not found".to_string())?;
            println!("{}", to_string_pretty(models).map_err(|e| e.to_string())?);
        }
        "capabilities" => {
            if args.len() != 5 {
                return Err(usage());
            }
            let capabilities = library
                .get_model_capabilities(&args[2], &args[3], &args[4])
                .ok_or_else(|| "Capabilities not found".to_string())?;
            println!(
                "{}",
                to_string_pretty(capabilities).map_err(|e| e.to_string())?
            );
        }
        "scpi" => {
            if args.len() != 5 {
                return Err(usage());
            }
            let scpi = library
                .get_model_scpi(&args[2], &args[3], &args[4])
                .ok_or_else(|| "SCPI commands not found".to_string())?;
            println!("{}", to_string_pretty(&scpi).map_err(|e| e.to_string())?);
        }
        "connections" => {
            if args.len() != 5 {
                return Err(usage());
            }
            let connections = library
                .get_supported_connection_types(&args[2], &args[3], &args[4])
                .ok_or_else(|| "Connection types not found".to_string())?;
            println!(
                "{}",
                to_string_pretty(&connections).map_err(|e| e.to_string())?
            );
        }
        _ => return Err(usage()),
    }

    Ok(())
}

fn usage() -> String {
    [
        "Usage:",
        "  cargo run --manifest-path backend-rust/Cargo.toml -- types",
        "  cargo run --manifest-path backend-rust/Cargo.toml -- series <type_name>",
        "  cargo run --manifest-path backend-rust/Cargo.toml -- models <type_name> <series_id>",
        "  cargo run --manifest-path backend-rust/Cargo.toml -- capabilities <type_name> <series_id> <model_id>",
        "  cargo run --manifest-path backend-rust/Cargo.toml -- scpi <type_name> <series_id> <model_id>",
        "  cargo run --manifest-path backend-rust/Cargo.toml -- connections <type_name> <series_id> <model_id>",
    ]
    .join("\n")
}

fn default_library_path() -> Result<PathBuf, String> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest_dir
        .parent()
        .ok_or_else(|| "Unable to determine repository root".to_string())?;
    Ok(repo_root
        .join("Instruments_LIB")
        .join("instruments_lib.json"))
}
