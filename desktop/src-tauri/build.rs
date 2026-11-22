fn main() {
    let source = std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap())
        .join("../../backend/build-info.json");
    println!("cargo:rerun-if-changed={}", source.display());
    let info = match std::fs::read_to_string(&source) {
        Ok(text) => {
            let value: serde_json::Value = serde_json::from_str(&text).expect("invalid backend build-info JSON");
            for key in ["source_sha", "source_tree"] {
                let hash = value[key].as_str().expect("missing backend source identity");
                assert!(hash.len() == 40 && hash.bytes().all(|byte| byte.is_ascii_hexdigit()), "invalid backend source identity");
            }
            assert_eq!(value["version"].as_str(), Some(env!("CARGO_PKG_VERSION")), "backend and shell versions differ");
            if std::env::var("PROFILE").as_deref() == Ok("release") {
                let git = |arguments: &[&str]| {
                    let output = std::process::Command::new("git").args(arguments).output().expect("git is required for candidate provenance");
                    assert!(output.status.success(), "cannot verify native source checkout");
                    String::from_utf8(output.stdout).unwrap().trim().to_string()
                };
                assert_eq!(git(&["rev-parse", "HEAD"]), value["source_sha"].as_str().unwrap(), "rebuild backend for the current native source");
                assert!(git(&["status", "--porcelain", "--untracked-files=all"]).is_empty(), "native candidate requires a clean checkout");
            }
            text
        }
        Err(_) if std::env::var("PROFILE").as_deref() == Ok("debug") => {
            "{\"schema_version\":1,\"channel\":\"source\",\"source_sha\":null}".to_string()
        }
        Err(error) => panic!("Build the frozen backend from the same clean checkout before the native release build: {error}"),
    };
    std::fs::write(std::path::PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("kellai-build-info.json"), info)
        .expect("cannot embed native source identity");
    tauri_build::build()
}
