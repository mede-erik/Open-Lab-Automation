use serde_json::{Map, Value};
use std::fs;
use std::path::Path;

const TYPE_MAPPINGS: [(&str, &str); 4] = [
    ("power_supply", "power_supplies_series"),
    ("datalogger", "dataloggers_series"),
    ("oscilloscope", "oscilloscopes_series"),
    ("electronic_load", "electronic_loads_series"),
];

pub struct InstrumentLibrary {
    instruments: Map<String, Value>,
}

impl InstrumentLibrary {
    pub fn load_from_file(path: impl AsRef<Path>) -> Result<Self, String> {
        let raw = fs::read_to_string(&path)
            .map_err(|e| format!("Unable to read {}: {e}", path.as_ref().display()))?;
        let parsed: Value = serde_json::from_str(&raw)
            .map_err(|e| format!("Invalid JSON in {}: {e}", path.as_ref().display()))?;

        let instruments = if let Some(library) = parsed
            .as_object()
            .and_then(|root| root.get("instrument_library"))
            .and_then(|value| value.as_object())
        {
            library.clone()
        } else if let Some(library) = parsed.as_object() {
            library.clone()
        } else {
            return Err("Instrument library must be a JSON object".to_string());
        };

        Ok(Self { instruments })
    }

    pub fn get_all_types(&self) -> Vec<&'static str> {
        let mut types: Vec<&'static str> = self
            .instruments
            .keys()
            .filter_map(|key| Self::type_for_key(key))
            .collect();
        types.sort_unstable();
        types.dedup();
        types
    }

    pub fn get_series(&self, type_name: &str) -> Option<&Vec<Value>> {
        self.instruments
            .get(Self::key_for_type(type_name)?)
            .and_then(Value::as_array)
    }

    pub fn get_models(&self, type_name: &str, series_id: &str) -> Option<&Vec<Value>> {
        let series = self
            .get_series(type_name)?
            .iter()
            .find(|entry| entry.get("series_id").and_then(Value::as_str) == Some(series_id))?;
        series.get("models")?.as_array()
    }

    pub fn get_model_capabilities(
        &self,
        type_name: &str,
        series_id: &str,
        model_id: &str,
    ) -> Option<&Value> {
        self.find_model(type_name, series_id, model_id)
            .and_then(|model| model.get("capabilities"))
    }

    pub fn get_model_scpi(
        &self,
        type_name: &str,
        series_id: &str,
        model_id: &str,
    ) -> Option<Map<String, Value>> {
        let series = self
            .get_series(type_name)?
            .iter()
            .find(|entry| entry.get("series_id").and_then(Value::as_str) == Some(series_id))?;

        let mut merged = Map::new();

        if let Some(common) = series
            .get("common_scpi_commands")
            .and_then(Value::as_object)
        {
            for (key, value) in common {
                merged.insert(key.clone(), value.clone());
            }
        }

        let model = series
            .get("models")?
            .as_array()?
            .iter()
            .find(|entry| entry.get("id").and_then(Value::as_str) == Some(model_id))?;

        if let Some(specific) = model.get("scpi_commands").and_then(Value::as_object) {
            for (key, value) in specific {
                merged.insert(key.clone(), value.clone());
            }
        }

        Some(merged)
    }

    pub fn get_supported_connection_types(
        &self,
        type_name: &str,
        series_id: &str,
        model_id: &str,
    ) -> Option<Vec<String>> {
        let model = self.find_model(type_name, series_id, model_id)?;

        let connection_types = model
            .get("interface")?
            .get("supported_connection_types")?
            .as_array()?
            .iter()
            .filter_map(|entry| entry.get("type").and_then(Value::as_str))
            .map(str::to_string)
            .collect();

        Some(connection_types)
    }

    fn find_model(&self, type_name: &str, series_id: &str, model_id: &str) -> Option<&Value> {
        self.get_models(type_name, series_id)?
            .iter()
            .find(|entry| entry.get("id").and_then(Value::as_str) == Some(model_id))
    }

    fn key_for_type(type_name: &str) -> Option<&'static str> {
        TYPE_MAPPINGS
            .iter()
            .find(|(name, _)| *name == type_name)
            .map(|(_, key)| *key)
    }

    fn type_for_key(key: &str) -> Option<&'static str> {
        TYPE_MAPPINGS
            .iter()
            .find(|(_, mapped_key)| *mapped_key == key)
            .map(|(name, _)| *name)
    }
}

#[cfg(test)]
mod tests {
    use super::InstrumentLibrary;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn write_temp_library_file() -> PathBuf {
        let content = include_str!("../../Instruments_LIB/instruments_lib.json");
        let unique_suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock before UNIX_EPOCH")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "open-lab-instruments-test-{}-{}.json",
            std::process::id(),
            unique_suffix
        ));
        fs::write(&path, content).expect("failed to write test file");
        path
    }

    #[test]
    fn loads_instrument_library() {
        let path = write_temp_library_file();
        let library = InstrumentLibrary::load_from_file(&path).expect("load failed");

        let series = library.get_series("power_supply").expect("missing series");
        assert!(!series.is_empty());

        let _ = fs::remove_file(path);
    }

    #[test]
    fn returns_scpi_and_connections() {
        let path = write_temp_library_file();
        let library = InstrumentLibrary::load_from_file(&path).expect("load failed");

        let scpi = library
            .get_model_scpi("power_supply", "OWON_ODP_Series", "PSU_OWON_ODP3033")
            .expect("scpi missing");
        assert!(scpi.contains_key("set_voltage"));

        let connections = library
            .get_supported_connection_types("power_supply", "OWON_ODP_Series", "PSU_OWON_ODP3033")
            .expect("connections missing");
        assert!(connections.iter().any(|entry| entry == "LXI"));

        let _ = fs::remove_file(path);
    }
}
