use base64::{engine::general_purpose::STANDARD, Engine};
use ed25519_dalek::{Signature, VerifyingKey};
use serde_json::{json, Value};
use std::{fs, io::Read, path::PathBuf, process::Command, sync::atomic::{AtomicBool, Ordering}, time::Duration};
#[cfg(windows)]
use std::os::windows::process::CommandExt;

pub static INSTALLING: AtomicBool = AtomicBool::new(false);
const ENDPOINT: &str = "https://deadlockporting.app/updates/windows.json";
const MAX_BYTES: u64 = 150 * 1024 * 1024;
fn client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder().user_agent(concat!("DeadlockPorting/", env!("CARGO_PKG_VERSION"))).https_only(true).timeout(Duration::from_secs(180))
        .connect_timeout(Duration::from_secs(10)).redirect(reqwest::redirect::Policy::custom(|attempt| {
            let url = attempt.url();
            if attempt.previous().len() < 3 && url.scheme() == "https"
                && matches!(url.host_str(), Some("deadlockporting.app" | "www.deadlockporting.app"))
                && url.port_or_known_default() == Some(443) {
                attempt.follow()
            } else { attempt.stop() }
        }))
        .build().map_err(|e| e.to_string())
}
fn read_limited(response: reqwest::blocking::Response, limit: u64) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    response.error_for_status().map_err(|e| e.to_string())?.take(limit + 1).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    if bytes.len() as u64 > limit { return Err("Update exceeds the size limit".into()); }
    Ok(bytes)
}
fn newer(version: &str) -> Result<bool, String> {
    let candidate = semver::Version::parse(version).map_err(|_| "Invalid update version")?;
    Ok(candidate > semver::Version::parse(env!("CARGO_PKG_VERSION")).unwrap() && candidate.pre.is_empty())
}
fn validate_manifest(m: &Value) -> Result<(), String> {
    let version = m["version"].as_str().ok_or("Missing update version")?;
    semver::Version::parse(version).map_err(|_| "Invalid update version")?;
    let url = reqwest::Url::parse(m["url"].as_str().ok_or("Missing update URL")?).map_err(|_| "Invalid update URL")?;
    if url.scheme() != "https" || !matches!(url.host_str(), Some("deadlockporting.app" | "www.deadlockporting.app")) || url.port_or_known_default() != Some(443)
        || !url.username().is_empty() || url.password().is_some() || !url.path().starts_with("/downloads/") || !url.path().ends_with(".exe") {
        return Err("Update URL is not trusted".into());
    }
    let size = m["bytes"].as_u64().ok_or("Missing update size")?;
    if !(1024..=MAX_BYTES).contains(&size) { return Err("Invalid update size".into()); }
    if m["signature"].as_str().unwrap_or("").is_empty() { return Err("Missing update signature".into()); }
    Ok(())
}
fn manifest() -> Result<Value, String> {
    let bytes = read_limited(client()?.get(ENDPOINT).header("Cache-Control", "no-cache").send().map_err(|e| e.to_string())?, 16384)?;
    let m: Value = serde_json::from_slice(&bytes).map_err(|_| "Invalid update response")?;
    validate_manifest(&m)?;
    Ok(m)
}
fn verify(m: &Value, bytes: &[u8]) -> Result<(), String> {
    if bytes.len() as u64 != m["bytes"].as_u64().unwrap_or(0) || !bytes.starts_with(b"MZ") { return Err("Update download is incomplete".into()); }
    let public = STANDARD.decode(include_str!("../update-public-key.txt").trim()).map_err(|_| "Invalid public key")?;
    let key = VerifyingKey::from_bytes(&public.try_into().map_err(|_| "Invalid public key")?).map_err(|_| "Invalid public key")?;
    let signature = STANDARD.decode(m["signature"].as_str().unwrap_or("")).map_err(|_| "Invalid update signature")?;
    let signature = Signature::from_slice(&signature).map_err(|_| "Invalid update signature")?;
    let mut signed = format!("{}\n", m["version"].as_str().unwrap_or("")).into_bytes();
    signed.extend_from_slice(bytes);
    key.verify_strict(&signed, &signature).map_err(|_| "Update signature verification failed".into())
}
#[tauri::command]
pub async fn check_update() -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let m = manifest()?;
        Ok(json!({"current":env!("CARGO_PKG_VERSION"), "version":m["version"], "available":newer(m["version"].as_str().unwrap())?}))
    }).await.map_err(|e| e.to_string())?
}
#[tauri::command]
pub async fn install_update(app: tauri::AppHandle, backend: tauri::State<'_, crate::Backend>) -> Result<(), String> {
    if INSTALLING.swap(true, Ordering::SeqCst) { return Err("An update is already in progress".into()); }
    let backend = backend.inner().clone();
    let result = tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
        if backend.request("state", Value::Null)?["busy"].as_bool().unwrap_or(true) { return Err("Wait for the export to finish before updating".into()); }
        let target = std::env::current_exe().map_err(|e| e.to_string())?;
        if target.with_extension("update-backup.exe").exists() || target.with_extension("update-new.exe").exists() {
            return Err("An earlier update left temporary files beside the app. Move the app to a clean folder and retry.".into());
        }
        let probe = target.with_extension(format!("update-check-{}", std::process::id()));
        fs::OpenOptions::new().write(true).create_new(true).open(&probe)
            .map_err(|_| "Move the app to a writable folder before updating".to_string())?;
        fs::remove_file(probe).map_err(|e| e.to_string())?;
        let m = manifest()?;
        if !newer(m["version"].as_str().unwrap())? { return Err("You already have the latest version".into()); }
        let bytes = read_limited(client()?.get(m["url"].as_str().unwrap()).send().map_err(|e| e.to_string())?, MAX_BYTES)?;
        verify(&m, &bytes)?;
        let dir = std::env::var_os("LOCALAPPDATA").map(PathBuf::from).ok_or("App data is unavailable")?
            .join("DeadlockPorting/updates").join(format!("{}-{}", m["version"].as_str().unwrap(), std::process::id()));
        fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        let helper = dir.join("update.exe");
        fs::write(&helper, bytes).map_err(|e| e.to_string())?;
        fs::write(dir.join("manifest.json"), serde_json::to_vec(&m).unwrap()).map_err(|e| e.to_string())?;
        let mut command = Command::new(helper);
        command.arg("--apply-update").arg(std::env::current_exe().map_err(|e| e.to_string())?).arg(std::process::id().to_string());
        #[cfg(windows)]
        command.creation_flags(0x08000000);
        command.spawn().map_err(|e| format!("Could not start updater: {e}"))?;
        Ok(())
    }).await.map_err(|e| e.to_string()).and_then(|r| r);
    if result.is_ok() { app.exit(0); } else { INSTALLING.store(false, Ordering::SeqCst); }
    result
}
pub fn apply(target: PathBuf, parent: u32) -> Result<(), String> {
    #[cfg(windows)]
    {
        #[link(name = "kernel32")]
        extern "system" {
            fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut std::ffi::c_void;
            fn WaitForSingleObject(handle: *mut std::ffi::c_void, millis: u32) -> u32;
            fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
        }
        unsafe {
            let handle = OpenProcess(0x00100000, 0, parent);
            if !handle.is_null() {
                let result = WaitForSingleObject(handle, 60000);
                CloseHandle(handle);
                if result != 0 { return Err("App did not close; update cancelled".into()); }
            }
        }
    }
    let source = std::env::current_exe().map_err(|e| e.to_string())?;
    let m: Value = serde_json::from_slice(&fs::read(source.with_file_name("manifest.json")).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    validate_manifest(&m)?;
    let bytes = fs::read(&source).map_err(|e| e.to_string())?;
    verify(&m, &bytes)?;
    if !target.is_absolute() || target.extension().and_then(|s| s.to_str()) != Some("exe") || target == source { return Err("Invalid update target".into()); }
    let next = target.with_extension("update-new.exe");
    let backup = target.with_extension("update-backup.exe");
    let mut output = fs::OpenOptions::new().write(true).create_new(true).open(&next).map_err(|e| format!("Cannot write beside the app: {e}"))?;
    use std::io::Write;
    output.write_all(&bytes).and_then(|_| output.sync_all()).map_err(|e| e.to_string())?;
    drop(output);
    let mut renamed = false;
    for _ in 0..120 {
        if !backup.exists() && fs::rename(&target, &backup).is_ok() { renamed = true; break; }
        std::thread::sleep(Duration::from_secs(1));
    }
    if !renamed { let _ = fs::remove_file(next); return Err("Could not replace the app. Close other copies and retry; the original is unchanged.".into()); }
    finish_swap(&target, &next, &backup, || Command::new(&target).spawn().map(|_| ()).map_err(|e| e.to_string()))
}
fn finish_swap(target: &std::path::Path, next: &std::path::Path, backup: &std::path::Path, launch: impl FnOnce() -> Result<(), String>) -> Result<(), String> {
    if let Err(error) = fs::rename(next, target) { let _ = fs::rename(&backup, &target); return Err(error.to_string()); }
    if let Err(error) = launch() {
        let _ = fs::remove_file(&target); let _ = fs::rename(&backup, &target);
        return Err(format!("Could not restart the app: {error}"));
    }
    let _ = fs::remove_file(backup);
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "requires the live update server"]
    fn live_update_manifest_is_reachable() {
        let m = manifest().expect("App HTTP client must follow the canonical domain redirect");
        assert!(m["version"].is_string());
        let response = client().unwrap().get(m["url"].as_str().unwrap()).send().unwrap();
        let bytes = read_limited(response, MAX_BYTES).unwrap();
        verify(&m, &bytes).expect("Live release must download and verify using the app client");
    }
    #[test]
    fn restores_original_if_restart_fails() {
        let folder = std::env::temp_dir().join(format!("deadlock-update-test-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        let target = folder.join("app.exe"); let next = folder.join("next.exe"); let backup = folder.join("backup.exe");
        fs::write(&backup, b"original").unwrap(); fs::write(&next, b"updated").unwrap();
        assert!(finish_swap(&target, &next, &backup, || Err("test launch failure".into())).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"original");
        fs::rename(&target, &backup).unwrap(); fs::write(&next, b"updated").unwrap();
        finish_swap(&target, &next, &backup, || Ok(())).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"updated"); assert!(!backup.exists());
        fs::remove_dir_all(folder).unwrap();
    }
    #[test]
    fn accepts_signed_payload_and_rejects_tampering() {
        let m: Value = serde_json::from_str(include_str!("update-test-manifest.json")).unwrap();
        let mut bytes = vec![0;1024]; bytes[..2].copy_from_slice(b"MZ");
        assert!(verify(&m, &bytes).is_ok());
        bytes[20] = 1; assert!(verify(&m, &bytes).is_err());
        bytes[20] = 0;
        let mut wrong_version = m.clone(); wrong_version["version"] = json!("0.10.11");
        assert!(verify(&wrong_version, &bytes).is_err());
    }
    #[test]
    fn rejects_unsafe_manifests_and_bad_signatures() {
        let mut m = json!({"version":"0.10.10","url":"https://deadlockporting.app/downloads/app.exe","bytes":1024,"signature":"invalid"});
        assert!(validate_manifest(&m).is_ok());
        assert!(verify(&m, &[0;1024]).is_err());
        m["url"] = json!("https://evil.example/downloads/app.exe"); assert!(validate_manifest(&m).is_err());
        assert!(newer("99.0.0").unwrap()); assert!(!newer(env!("CARGO_PKG_VERSION")).unwrap()); assert!(newer("invalid").is_err());
    }
}
