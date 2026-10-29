use std::{
    fs,
    io::Cursor,
    path::PathBuf,
    thread,
    time::{Duration, SystemTime},
};

const PAYLOAD: &[u8] = include_bytes!("../../package/payload.zip");
const FINGERPRINT: &str = include_str!("../../package/payload.sha256");

pub struct Runtime {
    pub data: PathBuf,
    pub port: PathBuf,
    pub python: PathBuf,
}

#[cfg(windows)]
pub fn message(text: &str, question: bool) -> bool {
    #[link(name = "user32")]
    extern "system" {
        fn MessageBoxW(
            window: *mut std::ffi::c_void,
            text: *const u16,
            caption: *const u16,
            flags: u32,
        ) -> i32;
    }
    let text: Vec<u16> = text.encode_utf16().chain(Some(0)).collect();
    let title: Vec<u16> = "Deadlock Porting".encode_utf16().chain(Some(0)).collect();
    unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            text.as_ptr(),
            title.as_ptr(),
            if question { 0x124 } else { 0x10 },
        ) == 6
    }
}

pub fn ensure_webview() -> Result<bool, String> {
    if tauri::webview_version().is_ok() {
        return Ok(true);
    }
    #[cfg(windows)]
    {
        if !message("Microsoft WebView2 is required to display this app. Download and install it from Microsoft now? An internet connection is required.", true) {
            return Ok(false);
        }
        let runtime = prepare()?;
        let status = std::process::Command::new(
            runtime
                .python
                .parent()
                .unwrap()
                .join("MicrosoftEdgeWebview2Setup.exe"),
        )
        .arg("/install")
        .status()
        .map_err(|e| e.to_string())?;
        if !status.success() || tauri::webview_version().is_err() {
            return Err("WebView2 could not be installed. Check your internet connection, install Microsoft WebView2, and reopen this app.".into());
        }
    }
    Ok(true)
}

struct LockFile(PathBuf);
impl Drop for LockFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

pub fn prepare() -> Result<Runtime, String> {
    let data = std::env::var_os("DEADLOCK_APP_DATA")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os("LOCALAPPDATA").map(|p| PathBuf::from(p).join("DeadlockPorting"))
        })
        .ok_or("Windows LOCALAPPDATA is unavailable")?;
    let cache = data.join("runtime");
    fs::create_dir_all(&cache).map_err(|e| e.to_string())?;
    let fingerprint = FINGERPRINT.trim();
    let root = cache.join(&fingerprint[..16]);
    let valid = || {
        root.join("runtime/python.exe").is_file()
            && root.join("port/tauri_bridge.py").is_file()
            && fs::read_to_string(root.join(".complete")).ok().as_deref() == Some(fingerprint)
    };
    if !valid() {
        let lock_path = cache.join(format!("{}.lock", &fingerprint[..16]));
        let mut acquired = None;
        for _ in 0..300 {
            match fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&lock_path)
            {
                Ok(_) => {
                    acquired = Some(LockFile(lock_path.clone()));
                    break;
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                    if valid() {
                        break;
                    }
                    if fs::metadata(&lock_path)
                        .and_then(|m| m.modified())
                        .ok()
                        .and_then(|t| t.elapsed().ok())
                        .is_some_and(|age| age > Duration::from_secs(120))
                    {
                        let _ = fs::remove_file(&lock_path);
                    }
                    thread::sleep(Duration::from_millis(100));
                }
                Err(e) => return Err(e.to_string()),
            }
        }
        if !valid() {
            let _lock = acquired
                .ok_or("Another app is still extracting its runtime. Try again shortly.")?;
            let stamp = SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .map_err(|e| e.to_string())?
                .as_nanos();
            let temporary = cache.join(format!(".unpack-{}-{stamp}", std::process::id()));
            fs::create_dir(&temporary).map_err(|e| e.to_string())?;
            let mut archive =
                zip::ZipArchive::new(Cursor::new(PAYLOAD)).map_err(|e| e.to_string())?;
            for index in 0..archive.len() {
                let mut entry = archive.by_index(index).map_err(|e| e.to_string())?;
                let relative = entry.enclosed_name().ok_or("Unsafe runtime archive path")?;
                let target = temporary.join(relative);
                if entry.is_dir() {
                    fs::create_dir_all(&target).map_err(|e| e.to_string())?;
                } else {
                    if let Some(parent) = target.parent() {
                        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
                    }
                    let mut output = fs::File::create(&target).map_err(|e| e.to_string())?;
                    std::io::copy(&mut entry, &mut output).map_err(|e| e.to_string())?;
                }
            }
            fs::write(temporary.join(".complete"), fingerprint).map_err(|e| e.to_string())?;
            if root.exists() {
                if root.parent() != Some(cache.as_path()) {
                    return Err("Invalid runtime cache location".into());
                }
                fs::remove_dir_all(&root).map_err(|e| e.to_string())?;
            }
            fs::rename(&temporary, &root).map_err(|e| e.to_string())?;
        }
    }
    Ok(Runtime {
        data,
        port: root.join("port"),
        python: root.join("runtime/python.exe"),
    })
}
