#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::{
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{Arc, Mutex},
};
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

struct Worker {
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
}

mod runtime;
mod presence;
mod updater;

impl Worker {
    fn start() -> Result<Self, String> {
        let runtime = runtime::prepare()?;
        let port = runtime.port;
        let python = runtime.python;
        let log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(runtime.data.join("tauri-backend.log"))
            .map_err(|e| e.to_string())?;
        let mut command = Command::new(python);
        command
            .arg("-u")
            .arg(port.join("tauri_bridge.py"))
            .current_dir(&port)
            .env("DEADLOCK_DATA_DIR", &runtime.data)
            .env_remove("PYTHONHOME")
            .env_remove("PYTHONPATH")
            .env_remove("DEADLOCK_HELPERS")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(log);
        #[cfg(windows)]
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        let mut child = command
            .spawn()
            .map_err(|e| format!("Could not start export worker: {e}"))?;
        let input = child.stdin.take().ok_or("Worker stdin unavailable")?;
        let output = BufReader::new(child.stdout.take().ok_or("Worker stdout unavailable")?);
        Ok(Self {
            child,
            input,
            output,
        })
    }

    fn request(&mut self, operation: &str, data: Value) -> Result<Value, String> {
        serde_json::to_writer(
            &mut self.input,
            &json!({"operation": operation, "data": data}),
        )
        .map_err(|e| e.to_string())?;
        self.input
            .write_all(b"\n")
            .and_then(|_| self.input.flush())
            .map_err(|e| e.to_string())?;
        let mut line = String::new();
        if self
            .output
            .read_line(&mut line)
            .map_err(|e| e.to_string())?
            == 0
        {
            return Err(
                "Export worker stopped. See the app-data tauri-backend.log, then restart the app."
                    .into(),
            );
        }
        let response: Value =
            serde_json::from_str(&line).map_err(|e| format!("Invalid worker response: {e}"))?;
        if let Some(error) = response.get("error") {
            return Err(error.as_str().unwrap_or("Worker error").into());
        }
        Ok(response["result"].clone())
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        let _ = self.request("shutdown", Value::Null);
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Clone, Default)]
struct Backend(Arc<Mutex<Option<Worker>>>);

impl Backend {
    fn request(&self, operation: &str, data: Value) -> Result<Value, String> {
        let mut worker = self.0.lock().map_err(|_| "Worker lock failed")?;
        if operation == "export" && updater::INSTALLING.load(std::sync::atomic::Ordering::SeqCst) {
            return Err("An app update is in progress".into());
        }
        if worker.is_none() {
            *worker = Some(Worker::start()?);
        }
        worker.as_mut().unwrap().request(operation, data)
    }
}

#[tauri::command]
fn update_presence(state: tauri::State<'_, presence::Presence>, model: String, category: String, exporting: bool) {
    state.update(model, category, exporting);
}

#[tauri::command]
async fn window_action(window: tauri::WebviewWindow, action: String) -> Result<(), String> {
    let result = match action.as_str() {
        "close" => window.close(),
        "minimize" => window.minimize(),
        "maximize" => match window.is_maximized() {
            Ok(true) => window.unmaximize(),
            Ok(false) => window.maximize(),
            Err(error) => return Err(error.to_string()),
        },
        "drag" => window.start_dragging(),
        _ => return Err("Unknown window action".into()),
    };
    result.map_err(|error| error.to_string())
}

#[tauri::command]
async fn backend(
    operation: String,
    data: Option<Value>,
    state: tauri::State<'_, Backend>,
) -> Result<Value, String> {
    if ![
        "catalog",
        "models",
        "model_info",
        "previews",
        "portrait",
        "settings",
        "blender_projects",
        "scan_installations",
        "save_settings",
        "state",
        "export",
    ]
    .contains(&operation.as_str())
    {
        return Err("Unsupported operation".into());
    }
    let worker = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        worker.request(&operation, data.unwrap_or(Value::Null))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn choose_blender_project(app: tauri::AppHandle) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .add_filter("Blender project", &["blend"])
            .blocking_pick_file()
            .map(|file| {
                file.into_path()
                    .map(|path| path.to_string_lossy().into_owned())
                    .map_err(|e| e.to_string())
            })
            .transpose()
    })
    .await
    .map_err(|e| e.to_string())?
}

fn standalone_test() -> Result<Value, String> {
    let runtime = runtime::prepare()?;
    let backend = Backend::default();
    let detected = backend.request("scan_installations", Value::Null)?;
    let settings = backend.request("settings", Value::Null)?;
    let models = backend.request("models", Value::Null)?;
    let portrait = backend.request("portrait", json!({"key":"haze"}))?;
    if !portrait
        .as_str()
        .is_some_and(|p| p.starts_with("data:image/png;base64,"))
    {
        return Err("Bundled portrait decoder failed".into());
    }
    let mut result = json!({"ok":true,"python":runtime.python,"port":runtime.port,
        "data":runtime.data,"detected":detected,"settings":settings,"models":models["counts"]});
    if std::env::args().any(|a| a == "--verify-export") {
        backend.request(
            "export",
            json!({"model":"models/heroes_staging/haze/haze.vmdl_c",
            "format":"blend","controls":true,"open_blender":false}),
        )?;
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(180);
        loop {
            let state = backend.request("state", Value::Null)?;
            if state["busy"] == false {
                if !state["error"].is_null() {
                    return Err(state["log"].to_string());
                }
                result["export"] = state["result"].clone();
                break;
            }
            if std::time::Instant::now() > deadline {
                return Err("Standalone export test timed out".into());
            }
            std::thread::sleep(std::time::Duration::from_millis(250));
        }
    }
    Ok(result)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if let Some(index) = args.iter().position(|a| a == "--apply-update") {
        let result = args.get(index + 1).ok_or("Missing update target".to_string())
            .and_then(|target| {
                let parent = args.get(index + 2).and_then(|pid| pid.parse::<u32>().ok()).ok_or("Missing parent process".to_string())?;
                updater::apply(std::path::PathBuf::from(target), parent)
            });
        if let Err(error) = result { runtime::message(&format!("Update could not finish: {error}"), false); }
        return;
    }
    if let Some(index) = args.iter().position(|a| a == "--self-test") {
        let result = standalone_test();
        let report = match &result {
            Ok(value) => value.clone(),
            Err(error) => json!({"ok":false,"error":error}),
        };
        if let Some(path) = args.get(index + 1) {
            if !path.starts_with("--") {
                let _ = std::fs::write(path, serde_json::to_vec_pretty(&report).unwrap());
            }
        }
        println!("{report}");
        std::process::exit(if result.is_ok() { 0 } else { 1 });
    }
    match runtime::ensure_webview() {
        Ok(true) => {}
        Ok(false) => return,
        Err(error) => {
            #[cfg(windows)]
            runtime::message(&error, false);
            return;
        }
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Backend::default())
        .manage(presence::Presence::start())
        .invoke_handler(tauri::generate_handler![
            backend,
            choose_blender_project,
            window_action,
            update_presence,
            updater::check_update,
            updater::install_update
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let backend = window.state::<Backend>();
                if let Ok(mut guard) = backend.0.lock() {
                    if let Some(worker) = guard.as_mut() {
                        if worker
                            .request("state", Value::Null)
                            .ok()
                            .and_then(|s| s["busy"].as_bool())
                            .unwrap_or(false)
                        {
                            api.prevent_close();
                            let _ = worker.request("close_pending", Value::Null);
                        }
                    }
                };
            }
        })
        .build(tauri::generate_context!())
        .expect("Could not start Deadlock Porting");
    app.run(|app, event| {
        if let tauri::RunEvent::Exit = event {
            if let Ok(mut worker) = app.state::<Backend>().0.lock() {
                *worker = None;
            };
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn worker_roundtrip_reads_real_catalog_and_portrait() {
        let backend = Backend::default();
        let settings = backend.request("settings", Value::Null).unwrap();
        assert!(settings["blender"]
            .as_str()
            .unwrap()
            .ends_with("blender.exe"));
        let heroes = backend.request("catalog", Value::Null).unwrap();
        assert!(heroes
            .as_array()
            .unwrap()
            .iter()
            .any(|h| h["name"] == "Haze"));
        let portrait = backend.request("portrait", json!({"key": "haze"})).unwrap();
        assert!(portrait
            .as_str()
            .unwrap()
            .starts_with("data:image/png;base64,iVBOR"));
        assert_eq!(
            backend.request("state", Value::Null).unwrap()["busy"],
            false
        );
        assert!(backend
            .request("portrait", json!({"key": "../bad"}))
            .is_err());
        let models = backend.request("models", Value::Null).unwrap();
        assert!(models["counts"]["all"].as_u64().unwrap() > 6000);
        for category in ["props", "npcs", "map"] {
            assert!(models["counts"][category].as_u64().unwrap() > 0);
        }
        let shelf = backend
            .request(
                "model_info",
                json!({"model": "models/props/artifact_shelf01.vmdl_c"}),
            )
            .unwrap();
        assert_eq!(shelf["skinned"], false);
        assert_eq!(shelf["exportable"], true);
        let empty = backend
            .request("model_info", json!({"model": "models/null.vmdl_c"}))
            .unwrap();
        assert_eq!(empty["exportable"], false);
        let previews = backend
            .request(
                "previews",
                json!({"models": ["models/props/bottle_d.vmdl_c"], "generate": false}),
            )
            .unwrap();
        assert_eq!(previews[0]["model"], "models/props/bottle_d.vmdl_c");
        assert!(previews[0]["status"].is_string());
    }
}
